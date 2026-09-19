#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_cluster_menu (){
    echo
    echo '==================== 团簇/分子 ATOMIC_VELOCITIES 生成 =================='
    echo "  0) 立即生成 ATOMICs_VELOCITIES 文件"
    echo "  1) 设置总动能，当前值：${cv_energy} eV"
    echo "  2) 设置速度方向，当前值：${cv_direction}"
    echo "  3) 返回"
    echo '==========================================================================='
}

function qe_element_mass_from_symbol (){
    local sym="$1"
    case "$sym" in
        H) echo 1.008;; He) echo 4.0026;; Li) echo 6.94;; Be) echo 9.0122;; B) echo 10.81;; C) echo 12.011;; N) echo 14.007;; O) echo 15.999;; F) echo 18.998;; Ne) echo 20.180;;
        Na) echo 22.990;; Mg) echo 24.305;; Al) echo 26.982;; Si) echo 28.085;; P) echo 30.974;; S) echo 32.06;; Cl) echo 35.45;; Ar) echo 39.948;;
        K) echo 39.098;; Ca) echo 40.078;; Sc) echo 44.956;; Ti) echo 47.867;; V) echo 50.942;; Cr) echo 51.996;; Mn) echo 54.938;; Fe) echo 55.845;; Co) echo 58.933;; Ni) echo 58.693;;
        Cu) echo 63.546;; Zn) echo 65.38;; Ga) echo 69.723;; Ge) echo 72.630;; As) echo 74.922;; Se) echo 78.971;; Br) echo 79.904;; Kr) echo 83.798;;
        Rb) echo 85.468;; Sr) echo 87.62;; Y) echo 88.906;; Zr) echo 91.244;; Nb) echo 92.906;; Mo) echo 95.95;; Tc) echo 98;; Ru) echo 101.07;; Rh) echo 102.91;; Pd) echo 106.42;; Ag) echo 107.87;; Cd) echo 112.41;;
        In) echo 114.82;; Sn) echo 118.71;; Sb) echo 121.76;; Te) echo 127.60;; I) echo 126.90;; Xe) echo 131.29;; Cs) echo 132.91;; Ba) echo 137.33;; La) echo 138.91;;
        Ce) echo 140.12;; Pr) echo 140.91;; Nd) echo 144.24;; Pm) echo 145;; Sm) echo 150.36;; Eu) echo 151.96;; Gd) echo 157.25;; Tb) echo 158.93;; Dy) echo 162.50;; Ho) echo 164.93;; Er) echo 167.26;;
        Tm) echo 168.93;; Yb) echo 173.05;; Lu) echo 174.97;; Hf) echo 178.49;; Ta) echo 180.95;; W) echo 183.84;; Re) echo 186.21;; Os) echo 190.23;; Ir) echo 192.22;; Pt) echo 195.08;; Au) echo 196.97;; Hg) echo 200.59;;
        Tl) echo 204.38;; Pb) echo 207.2;; Bi) echo 208.98;; Po) echo 209;; At) echo 210;; Rn) echo 222;;
        *) return 1;;
    esac
}

function qe_cluster_parse_cif_symbols (){
    awk '
        BEGIN{in_loop=0; in_atom=0; nhead=0; type_col=0; label_col=0}
        /^[ \t]*loop_[ \t]*$/ {in_loop=1; in_atom=0; nhead=0; type_col=0; label_col=0; next}
        in_loop && /^[ \t]*_atom_site_/ {
            nhead++
            h=$1
            if(h=="_atom_site_type_symbol") type_col=nhead
            if(h=="_atom_site_label") label_col=nhead
            in_atom=1
            next
        }
        in_loop && in_atom && /^[ \t]*_/ {next}
        in_loop && in_atom && NF>0 {
            if($1 ~ /^#/) next
            if($1=="loop_" || $1 ~ /^data_/) exit
            col=(type_col>0 ? type_col : label_col)
            if(col>0 && col<=NF){
                sym=$col
                gsub(/[\047\"]/,"",sym)
                # If only labels such as C1/F2 are present, strip trailing digits.
                sub(/[0-9]+$/, "", sym)
                if(sym ~ /^[A-Z][a-z]?$/) print sym
            }
        }
    ' "$fname1"
}

function qe_cluster_parse_multiwfn_symbols (){
    local temp_dir="$1" tmpfile="$1/${prefix}_QE.tmp"
    local natm begatmpos endatmpos
    require_multiwfn || return 1
    qbox_multiwfn "$fname1" << EOF &> /dev/null
100
2
26
${tmpfile}
0
q
EOF
    [ -f "$tmpfile" ] || return 1
    natm=`grep -m 1 'nat' "$tmpfile" | awk '{print $2}' | tr -d ','`
    begatmpos=`grep -n 'ATOMIC_POSITIONS' "$tmpfile" | head -n 1 | awk -F : '{print $1 + 1}'`
    [ -n "$natm" ] && [ -n "$begatmpos" ] || return 1
    endatmpos=$((${begatmpos} + ${natm} - 1))
    sed -n "${begatmpos},${endatmpos}p" "$tmpfile" | awk '{print $1}'
}

function qe_cluster_generate_velocities (){
    local temp_dir="$1" symbols_file="$1/symbols" masses_file="$1/masses" sym
    local mass total_mass_amu vx vy vz e_ha total_mass_me dir_norm

    echo
    echo ' 正在解析团簇/分子的原子符号....'

    qe_cluster_parse_cif_symbols > "$symbols_file"
    if [ ! -s "$symbols_file" ]; then
        echo ' 直接解析 CIF 失败，正在尝试使用 Multiwfn 解析....'
        qe_cluster_parse_multiwfn_symbols "$temp_dir" >"$symbols_file"
    fi

    if [ ! -s "$symbols_file" ]; then
        echo
        echo " 错误：无法从 '$fname1' 解析原子符号。"
        return 1
    fi

    : > "$masses_file" || return 1
    while IFS= read -r sym; do
        mass="$(qe_element_mass_from_symbol "$sym")"
        if [ -z "$mass" ] || [[ ! "$mass" =~ ^[+]?[0-9]+([.][0-9]+)?$ ]]; then
            echo
            echo " 错误：脚本中未定义元素 '$sym' 的原子质量。"
            return 1
        fi
        printf '%s\n' "$mass" >> "$masses_file" || return 1
    done < "$symbols_file"
    total_mass_amu="$(awk '{sum += $1} END {printf "%.12f", sum}' "$masses_file")"

    if ! awk -v M="$total_mass_amu" 'BEGIN{exit !(M>0)}'; then
        echo
        echo " 错误：无法计算团簇/分子总质量。解析得到的质量为 '$total_mass_amu'。"
        return 1
    fi

    read -r vx vy vz e_ha total_mass_me dir_norm <<< "$(awk -v E="$cv_energy" -v DIR="$cv_direction" -v M="$total_mass_amu" '
        BEGIN{
            split(DIR,d," "); dx=d[1]+0.0; dy=d[2]+0.0; dz=d[3]+0.0;
            norm=sqrt(dx*dx+dy*dy+dz*dz);
            if(E<=0 || norm<=0){exit 3}
            eha=E/27.211386245988;
            mme=M*1822.888486209;
            v=sqrt(2.0*eha/mme);
            printf("%.12f %.12f %.12f %.12f %.12f %.12f", v*dx/norm, v*dy/norm, v*dz/norm, eha, mme, norm)
        }')"

    if [ -z "$vx" ]; then
        echo
        echo " 错误：动能或方向无效。Energy='${cv_energy}', direction='${cv_direction}'。"
        echo ' 动能必须大于 0，方向必须为非零向量。'
        rm -f "$symbols_file"
        return 1
    fi

    {
        echo 'ATOMIC_VELOCITIES a.u.'
        awk -v vx="$vx" -v vy="$vy" -v vz="$vz" '{printf("%-4s %15.9f %15.9f %15.9f\n", $1, vx, vy, vz)}' "$symbols_file"
    } > ATOMICs_VELOCITIES

    echo
    echo " 总动能：${cv_energy} eV"
    echo " 速度方向：${cv_direction}"
    echo " 团簇/分子总质量：${total_mass_amu} amu"
    echo " 输出文件：ATOMICs_VELOCITIES"
    echo
    echo ' 预览：'
    head -n 8 ATOMICs_VELOCITIES
    rm -f "$symbols_file"
}
function cluster_velocities (){
local cluster_velocity_status=0

if [ -z "$fname1" ]; then
    echo
    echo ' 请输入团簇/分子的 CIF 文件，例如 CHF3.cif。'
    read fname1
    while [ -z "$fname1" ]; do
        echo
        echo ' 请输入团簇/分子的 CIF 文件，例如 CHF3.cif。'
        read fname1
    done
    qe_set_input_path "$fname1" || return 1
fi

if [ ! -f "$fname1" ]; then
    echo
    echo " 错误：未找到输入文件 '$fname1'。"
    return 1
fi

qe_auto_convert_vasp_to_cif "$fname1" || return 1
fname1="$QE_AUTO_CONVERTED_CIF"

cv_energy='200'
cv_direction='0 0 -1'






cluster_velocities_choice=("0" "1" "2" "3")
while true; do
    qe_cluster_menu
    read cluster_velocities_arg
    while ! echo "${cluster_velocities_choice[@]}" | grep -wq "$cluster_velocities_arg"; do
        echo "请输入有效的功能编号..."
        read cluster_velocities_arg
    done

    case $cluster_velocities_arg in
        "0") qe_with_temp_dir qe_cluster_generate_velocities "$PWD" cluster-velocities
            cluster_velocity_status=$?
            break;;
        "1")
            echo ' 请输入总动能，单位 eV，例如 200'
            read input_energy
            if echo "$input_energy" | awk '{exit !($1>0)}'; then
                cv_energy="$input_energy"
            else
                echo ' 无效动能。请输入正数。'
            fi
            ;;
        "2")
            echo ' 请输入速度方向 x y z，例如 0 0 -1'
            read input_direction
            if echo "$input_direction" | awk 'NF==3{exit !((($1+0)^2+($2+0)^2+($3+0)^2)>0)} NF!=3{exit 1}'; then
                cv_direction="$input_direction"
            else
                echo ' 无效方向。请输入三个数字，并避免零向量。'
            fi
            ;;
        "3") return;;
    esac
done
return "$cluster_velocity_status"
}

