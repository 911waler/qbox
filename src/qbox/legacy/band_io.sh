#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_embedded_find_path (){
qbox_python -m qbox.io.kpath "$@"
}

function qe_embedded_plot_band (){
# The former heredoc was never a TTY. Preserve its default energy reference
# instead of introducing an extra interactive question after extraction.
qbox_python -m qbox.postprocess.band_plot "$@" </dev/null
}
 
#define atomic index with corresponding element	定义原子代号，储存在数组 atm[] 中
atm["1"]="H";atm["2"]="He";atm["3"]="Li";atm["4"]="Be";atm["5"]="B";atm["6"]="C";atm["7"]="N";\
atm["8"]="O";atm["9"]="F";atm["10"]="Ne";atm["11"]="Na";atm["12"]="Mg";atm["13"]="Al";atm["14"]="Si";\
atm["15"]="P";atm["16"]="S";atm["17"]="Cl";atm["18"]="Ar";atm["19"]="K";atm["20"]="Ca";atm["21"]="Sc";\
atm["22"]="Ti";atm["23"]="V";atm["24"]="Cr";atm["25"]="Mn";atm["26"]="Fe";atm["27"]="Co";atm["28"]="Ni";\
atm["29"]="Cu";atm["30"]="Zn";atm["31"]="Ga";atm["32"]="Ge";atm["33"]="As";atm["34"]="Se";atm["35"]="Br";\
atm["36"]="Kr";atm["37"]="Rb";atm["38"]="Sr";atm["39"]="Y";atm["40"]="Zr";atm["41"]="Nb";atm["42"]="Mo";\
atm["43"]="Tc";atm["44"]="Ru";atm["45"]="Rh";atm["46"]="Pd";atm["47"]="Ag";atm["48"]="Cd";atm["49"]="In";\
atm["50"]="Sn";atm["51"]="Sb";atm["52"]="Te";atm["53"]="I";atm["54"]="Xe";atm["55"]="Cs";atm["56"]="Ba";\
atm["57"]="La";atm["58"]="Ce";atm["59"]="Pr";atm["60"]="Nd";atm["61"]="Pm";atm["62"]="Sm";atm["63"]="Eu";\
atm["64"]="Gd";atm["65"]="Tb";atm["66"]="Dy";atm["67"]="Ho";atm["68"]="Er";atm["69"]="Tm";atm["70"]="Yb";\
atm["71"]="Lu";atm["72"]="Hf";atm["73"]="Ta";atm["74"]="W";atm["75"]="Re";atm["76"]="Os";atm["77"]="Ir";\
atm["78"]="Pt";atm["79"]="Au";atm["80"]="Hg";atm["81"]="Tl";atm["82"]="Pb";atm["83"]="Bi";atm["84"]="Po";\
atm["85"]="At";atm["86"]="Rn"
 
#define atomic mass (amu), stored in the built-in element table used by qbox
atmmass["1"]="1.008";atmmass["2"]="4.0026";atmmass["3"]="6.94";atmmass["4"]="9.0122";atmmass["5"]="10.81";atmmass["6"]="12.011";atmmass["7"]="14.007";\
atmmass["8"]="15.999";atmmass["9"]="18.998";atmmass["10"]="20.180";atmmass["11"]="22.990";atmmass["12"]="24.305";atmmass["13"]="26.982";atmmass["14"]="28.085";\
atmmass["15"]="30.974";atmmass["16"]="32.06";atmmass["17"]="35.45";atmmass["18"]="39.948";atmmass["19"]="39.098";atmmass["20"]="40.078";atmmass["21"]="44.956";\
atmmass["22"]="47.867";atmmass["23"]="50.942";atmmass["24"]="51.996";atmmass["25"]="54.938";atmmass["26"]="55.845";atmmass["27"]="58.933";atmmass["28"]="58.693";\
atmmass["29"]="63.546";atmmass["30"]="65.38";atmmass["31"]="69.723";atmmass["32"]="72.630";atmmass["33"]="74.922";atmmass["34"]="78.971";atmmass["35"]="79.904";\
atmmass["36"]="83.798";atmmass["37"]="85.468";atmmass["38"]="87.62";atmmass["39"]="88.906";atmmass["40"]="91.244";atmmass["41"]="92.906";atmmass["42"]="95.95";\
atmmass["43"]="98";atmmass["44"]="101.07";atmmass["45"]="102.91";atmmass["46"]="106.42";atmmass["47"]="107.87";atmmass["48"]="112.41";atmmass["49"]="114.82";\
atmmass["50"]="118.71";atmmass["51"]="121.76";atmmass["52"]="127.60";atmmass["53"]="126.90";atmmass["54"]="131.29";atmmass["55"]="132.91";atmmass["56"]="137.33";\
atmmass["57"]="138.91";atmmass["58"]="140.12";atmmass["59"]="140.91";atmmass["60"]="144.24";atmmass["61"]="145";atmmass["62"]="150.36";atmmass["63"]="151.96";\
atmmass["64"]="157.25";atmmass["65"]="158.93";atmmass["66"]="162.50";atmmass["67"]="164.93";atmmass["68"]="167.26";atmmass["69"]="168.93";atmmass["70"]="173.05";\
atmmass["71"]="174.97";atmmass["72"]="178.49";atmmass["73"]="180.95";atmmass["74"]="183.84";atmmass["75"]="186.21";atmmass["76"]="190.23";atmmass["77"]="192.22";\
atmmass["78"]="195.08";atmmass["79"]="196.97";atmmass["80"]="200.59";atmmass["81"]="204.38";atmmass["82"]="207.2";atmmass["83"]="208.98";atmmass["84"]="209";\
atmmass["85"]="210";atmmass["86"]="222"	
 
#define SSSP pseudopotentials library
SSSPlib["1"]="H.UPF";SSSPlib["2"]="He.upf";SSSPlib["3"]="Li.UPF";SSSPlib["4"]="Be.UPF";SSSPlib["5"]="B.UPF";SSSPlib["6"]="C.UPF";SSSPlib["7"]="N.UPF";\
SSSPlib["8"]="O.UPF";SSSPlib["9"]="F.UPF";SSSPlib["10"]="Ne.upf";SSSPlib["11"]="Na.UPF";SSSPlib["12"]="Mg.UPF";SSSPlib["13"]="Al.UPF";SSSPlib["14"]="Si.UPF";\
SSSPlib["15"]="P.UPF";SSSPlib["16"]="S.UPF";SSSPlib["17"]="Cl.UPF";SSSPlib["18"]="Ar.upf";SSSPlib["19"]="K.UPF";SSSPlib["20"]="Ca.UPF";SSSPlib["21"]="Sc.upf";\
SSSPlib["22"]="Ti.UPF";SSSPlib["23"]="V.UPF";SSSPlib["24"]="Cr.UPF";SSSPlib["25"]="Mn.UPF";SSSPlib["26"]="Fe.UPF";SSSPlib["27"]="Co.UPF";SSSPlib["28"]="Ni.UPF";\
SSSPlib["29"]="Cu.upf";SSSPlib["30"]="Zn.UPF";SSSPlib["31"]="Ga.UPF";SSSPlib["32"]="Ge.UPF";SSSPlib["33"]="As.UPF";SSSPlib["34"]="Se.UPF";SSSPlib["35"]="Br.UPF";\
SSSPlib["36"]="Kr.upf";SSSPlib["37"]="Rb.upf";SSSPlib["38"]="Sr.UPF";SSSPlib["39"]="Y.UPF";SSSPlib["40"]="Zr.UPF";SSSPlib["41"]="Nb.UPF";SSSPlib["42"]="Mo.upf";\
SSSPlib["43"]="Tc.upf";SSSPlib["44"]="Ru.upf";SSSPlib["45"]="Rh.upf";SSSPlib["46"]="Pd.upf";SSSPlib["47"]="Ag.upf";SSSPlib["48"]="Cd.UPF";SSSPlib["49"]="In.UPF";\
SSSPlib["50"]="Sn.UPF";SSSPlib["51"]="Sb.UPF";SSSPlib["52"]="Te.UPF";SSSPlib["53"]="I.UPF";SSSPlib["54"]="Xe.upf";SSSPlib["55"]="Cs.UPF";SSSPlib["56"]="Ba.UPF";\
SSSPlib["57"]="La.upf";SSSPlib["58"]="Ce.upf";SSSPlib["59"]="Pr.upf";SSSPlib["60"]="Nd.upf";SSSPlib["61"]="Pm.upf";SSSPlib["62"]="Sm.upf";SSSPlib["63"]="Eu.upf";\
SSSPlib["64"]="Gd.upf";SSSPlib["65"]="Tb.upf";SSSPlib["66"]="Dy.upf";SSSPlib["67"]="Ho.upf";SSSPlib["68"]="Er.upf";SSSPlib["69"]="Tm.upf";SSSPlib["70"]="Yb.upf";\
SSSPlib["71"]="Lu.upf";SSSPlib["72"]="Hf.upf";SSSPlib["73"]="Ta.UPF";SSSPlib["74"]="W.UPF";SSSPlib["75"]="Re.UPF";SSSPlib["76"]="Os.UPF";SSSPlib["77"]="Ir.UPF";\
SSSPlib["78"]="Pt.UPF";SSSPlib["79"]="Au.upf";SSSPlib["80"]="Hg.upf";SSSPlib["81"]="Tl.UPF";SSSPlib["82"]="Pb.UPF";SSSPlib["83"]="Bi.UPF";SSSPlib["84"]="Po.UPF";\
SSSPlib["85"]="At.upf";SSSPlib["86"]="Rn.UPF";SSSPlib["87"]="Fr.upf";SSSPlib["88"]="Ra.upf";SSSPlib["89"]="Ac.upf";SSSPlib["90"]="Th.upf";SSSPlib["91"]="Pa.upf";\
SSSPlib["92"]="U.upf";SSSPlib["93"]="Np.upf";SSSPlib["94"]="Pu.upf";SSSPlib["95"]="Am.upf";SSSPlib["96"]="Cm.upf";SSSPlib["97"]="Bk.upf";SSSPlib["98"]="Cf.upf";\
SSSPlib["99"]="Es.upf";SSSPlib["100"]="Fm.upf";SSSPlib["101"]="Md.upf";SSSPlib["102"]="No.upf";SSSPlib["103"]="Lr.upf";
 
#define PD04 pseudopotentials library
PD04lib["1"]="H.PD04.PBE.UPF";PD04lib["2"]="He.PD04.PBE.UPF";PD04lib["3"]="Li-s.PD04.PBE.UPF";PD04lib["4"]="Be-s.PD04.PBE.UPF";PD04lib["5"]="B.PD04.PBE.UPF";PD04lib["6"]="C.PD04.PBE.UPF";PD04lib["7"]="N.PD04.PBE.UPF";\
PD04lib["8"]="O.PD04.PBE.UPF";PD04lib["9"]="F.PD04.PBE.UPF";PD04lib["10"]="Ne.PD04.PBE.UPF";PD04lib["11"]="Na-sp.PD04.PBE.UPF";PD04lib["12"]="Mg.PD04.PBE.UPF";PD04lib["13"]="Al.PD04.PBE.UPF";PD04lib["14"]="Si.PD04.PBE.UPF";\
PD04lib["15"]="P.PD04.PBE.UPF";PD04lib["16"]="S.PD04.PBE.UPF";PD04lib["17"]="Cl.PD04.PBE.UPF";PD04lib["18"]="Ar.PD04.PBE.UPF";PD04lib["19"]="K-sp.PD04.PBE.UPF";PD04lib["20"]="Ca-sp.PD04.PBE.UPF";PD04lib["21"]="Sc-sp.PD04.PBE.UPF";\
PD04lib["22"]="Ti-sp.PD04.PBE.UPF";PD04lib["23"]="V-sp.PD04.PBE.UPF";PD04lib["24"]="Cr-sp.PD04.PBE.UPF";PD04lib["25"]="Mn-sp.PD04.PBE.UPF";PD04lib["26"]="Fe-sp.PD04.PBE.UPF";PD04lib["27"]="Co-sp.PD04.PBE.UPF";PD04lib["28"]="Ni-sp.PD04.PBE.UPF";\
PD04lib["29"]="Cu-sp.PD04.PBE.UPF";PD04lib["30"]="Zn.PD04.PBE.UPF";PD04lib["31"]="Ga-d.PD04.PBE.UPF";PD04lib["32"]="Ge-d.PD04.PBE.UPF";PD04lib["33"]="As.PD04.PBE.UPF";PD04lib["34"]="Se.PD04.PBE.UPF";PD04lib["35"]="Br.PD04.PBE.UPF";\
PD04lib["36"]="Kr.PD04.PBE.UPF";PD04lib["37"]="Rb-sp.PD04.PBE.UPF";PD04lib["38"]="Sr-sp.PD04.PBE.UPF";PD04lib["39"]="Y-sp.PD04.PBE.UPF";PD04lib["40"]="Zr-sp.PD04.PBE.UPF";PD04lib["41"]="Nb-sp.PD04.PBE.UPF";PD04lib["42"]="Mo-sp.PD04.PBE.UPF";\
PD04lib["43"]="Tc-sp.PD04.PBE.UPF";PD04lib["44"]="Ru-sp.PD04.PBE.UPF";PD04lib["45"]="Rh-sp.PD04.PBE.UPF";PD04lib["46"]="Pd-sp.PD04.PBE.UPF";PD04lib["47"]="Ag-sp.PD04.PBE.UPF";PD04lib["48"]="Cd.PD04.PBE.UPF";PD04lib["49"]="In.PD04.PBE.UPF";\
PD04lib["50"]="Sn.PD04.PBE.UPF";PD04lib["51"]="Sb.PD04.PBE.UPF";PD04lib["52"]="Te.PD04.PBE.UPF";PD04lib["53"]="I.PD04.PBE.UPF";PD04lib["54"]="Xe.PD04.PBE.UPF";PD04lib["55"]="Cs-sp.PD04.PBE.UPF";PD04lib["56"]="Ba-sp.PD04.PBE.UPF";\
PD04lib["57"]="La-sp.PD04.PBE.UPF";PD04lib["58"]="Ce-sp.PD04.PBE.UPF";PD04lib["59"]="Pr-sp.PD04.PBE.UPF";PD04lib["60"]="Nd-sp.PD04.PBE.UPF";PD04lib["61"]="Pm-sp.PD04.PBE.UPF";PD04lib["62"]="Sm-sp.PD04.PBE.UPF";PD04lib["63"]="Eu-sp.PD04.PBE.UPF";\
PD04lib["64"]="Gd-sp.PD04.PBE.UPF";PD04lib["65"]="Tb-sp.PD04.PBE.UPF";PD04lib["66"]="Dy-sp.PD04.PBE.UPF";PD04lib["67"]="Ho-sp.PD04.PBE.UPF";PD04lib["68"]="Er-sp.PD04.PBE.UPF";PD04lib["69"]="Tm-sp.PD04.PBE.UPF";PD04lib["70"]="Yb-sp.PD04.PBE.UPF";\
PD04lib["71"]="Lu-sp.PD04.PBE.UPF";PD04lib["72"]="Hf-sp.PD04.PBE.UPF";PD04lib["73"]="Ta-sp.PD04.PBE.UPF";PD04lib["74"]="W-sp.PD04.PBE.UPF";PD04lib["75"]="Re-sp.PD04.PBE.UPF";PD04lib["76"]="Os-sp.PD04.PBE.UPF";PD04lib["77"]="Ir-sp.PD04.PBE.UPF";\
PD04lib["78"]="Pt-sp.PD04.PBE.UPF";PD04lib["79"]="Au-sp.PD04.PBE.UPF";PD04lib["80"]="Hg.PD04.PBE.UPF";PD04lib["81"]="Tl-d.PD04.PBE.UPF";PD04lib["82"]="Pb-d.PD04.PBE.UPF";PD04lib["83"]="Bi-d.PD04.PBE.UPF";PD04lib["84"]="Po-d.PD04.PBE.UPF";\
PD04lib["85"]="At.upf";PD04lib["86"]="Rn.PD04.PBE.UPF";PD04lib["87"]="Fr.upf";PD04lib["88"]="Ra.upf";PD04lib["89"]="Ac.upf";PD04lib["90"]="Th.upf";PD04lib["91"]="Pa.upf";\
PD04lib["92"]="U.upf";PD04lib["93"]="Np.upf";PD04lib["94"]="Pu.upf";PD04lib["95"]="Am.upf";PD04lib["96"]="Cm.upf";PD04lib["97"]="Bk.upf";PD04lib["98"]="Cf.upf";\
PD04lib["99"]="Es.upf";PD04lib["100"]="Fm.upf";PD04lib["101"]="Md.upf";PD04lib["102"]="No.upf";PD04lib["103"]="Lr.upf";
 
#define SG15 pseudopotentials library
SG15lib["1"]="H.SG15.PBE.UPF";SG15lib["2"]="He.SG15.PBE.UPF";SG15lib["3"]="Li.SG15.PBE.UPF";SG15lib["4"]="Be.SG15.PBE.UPF";SG15lib["5"]="B.SG15.PBE.UPF";SG15lib["6"]="C.SG15.PBE.UPF";SG15lib["7"]="N.SG15.PBE.UPF";\
SG15lib["8"]="O.SG15.PBE.UPF";SG15lib["9"]="F.SG15.PBE.UPF";SG15lib["10"]="Ne.SG15.PBE.UPF";SG15lib["11"]="Na.SG15.PBE.UPF";SG15lib["12"]="Mg.SG15.PBE.UPF";SG15lib["13"]="Al.SG15.PBE.UPF";SG15lib["14"]="Si.SG15.PBE.UPF";\
SG15lib["15"]="P.SG15.PBE.UPF";SG15lib["16"]="S.SG15.PBE.UPF";SG15lib["17"]="Cl.SG15.PBE.UPF";SG15lib["18"]="Ar.SG15.PBE.UPF";SG15lib["19"]="K-sp.SG15.PBE.UPF";SG15lib["20"]="Ca.SG15.PBE.UPF";SG15lib["21"]="Sc.SG15.PBE.UPF";\
SG15lib["22"]="Ti.SG15.PBE.UPF";SG15lib["23"]="V.SG15.PBE.UPF";SG15lib["24"]="Cr.SG15.PBE.UPF";SG15lib["25"]="Mn.SG15.PBE.UPF";SG15lib["26"]="Fe.SG15.PBE.UPF";SG15lib["27"]="Co.SG15.PBE.UPF";SG15lib["28"]="Ni.SG15.PBE.UPF";\
SG15lib["29"]="Cu.SG15.PBE.UPF";SG15lib["30"]="Zn.SG15.PBE.UPF";SG15lib["31"]="Ga.SG15.PBE.UPF";SG15lib["32"]="Ge.SG15.PBE.UPF";SG15lib["33"]="As.SG15.PBE.UPF";SG15lib["34"]="Se.SG15.PBE.UPF";SG15lib["35"]="Br.SG15.PBE.UPF";\
SG15lib["36"]="Kr.SG15.PBE.UPF";SG15lib["37"]="Rb.SG15.PBE.UPF";SG15lib["38"]="Sr.SG15.PBE.UPF";SG15lib["39"]="Y.SG15.PBE.UPF";SG15lib["40"]="Zr.SG15.PBE.UPF";SG15lib["41"]="Nb.SG15.PBE.UPF";SG15lib["42"]="Mo.SG15.PBE.UPF";\
SG15lib["43"]="Tc.SG15.PBE.UPF";SG15lib["44"]="Ru.SG15.PBE.UPF";SG15lib["45"]="Rh.SG15.PBE.UPF";SG15lib["46"]="Pd.SG15.PBE.UPF";SG15lib["47"]="Ag.SG15.PBE.UPF";SG15lib["48"]="Cd.SG15.PBE.UPF";SG15lib["49"]="In.SG15.PBE.UPF";\
SG15lib["50"]="Sn.SG15.PBE.UPF";SG15lib["51"]="Sb.SG15.PBE.UPF";SG15lib["52"]="Te.SG15.PBE.UPF";SG15lib["53"]="I.SG15.PBE.UPF";SG15lib["54"]="Xe.SG15.PBE.UPF";SG15lib["55"]="Cs.SG15.PBE.UPF";SG15lib["56"]="Ba.SG15.PBE.UPF";\
SG15lib["57"]="La.SG15.PBE.UPF";SG15lib["58"]="Ce.upf";SG15lib["59"]="Pr.upf";SG15lib["60"]="Nd.upf";SG15lib["61"]="Pm.upf";SG15lib["62"]="Sm.upf";SG15lib["63"]="Eu.upf";\
SG15lib["64"]="Gd.upf";SG15lib["65"]="Tb.upf";SG15lib["66"]="Dy.upf";SG15lib["67"]="Ho.upf";SG15lib["68"]="Er.upf";SG15lib["69"]="Tm.upf";SG15lib["70"]="Yb.upf";\
SG15lib["71"]="Lu.upf";SG15lib["72"]="Hf.SG15.PBE.UPF";SG15lib["73"]="Ta.SG15.PBE.UPF";SG15lib["74"]="W.SG15.PBE.UPF";SG15lib["75"]="Re.SG15.PBE.UPF";SG15lib["76"]="Os.SG15.PBE.UPF";SG15lib["77"]="Ir.SG15.PBE.UPF";\
SG15lib["78"]="Pt.SG15.PBE.UPF";SG15lib["79"]="Au.SG15.PBE.UPF";SG15lib["80"]="Hg.SG15.PBE.UPF";SG15lib["81"]="Tl.SG15.PBE.UPF";SG15lib["82"]="Pb-d.SG15.PBE.UPF";SG15lib["83"]="Bi-d.SG15.PBE.UPF";SG15lib["84"]="Po.UPF";\
SG15lib["85"]="At.upf";SG15lib["86"]="Rn.UPF";SG15lib["87"]="Fr.upf";SG15lib["88"]="Ra.upf";SG15lib["89"]="Ac.upf";SG15lib["90"]="Th.upf";SG15lib["91"]="Pa.upf";\
SG15lib["92"]="U.upf";SG15lib["93"]="Np.upf";SG15lib["94"]="Pu.upf";SG15lib["95"]="Am.upf";SG15lib["96"]="Cm.upf";SG15lib["97"]="Bk.upf";SG15lib["98"]="Cf.upf";\
SG15lib["99"]="Es.upf";SG15lib["100"]="Fm.upf";SG15lib["101"]="Md.upf";SG15lib["102"]="No.upf";SG15lib["103"]="Lr.upf";
