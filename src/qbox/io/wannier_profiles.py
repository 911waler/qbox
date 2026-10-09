"""Validated, data-driven postprocessing templates for official W90 3.1.0.

Parameter spelling and dependencies are checked against the v3.1.0 sources:
https://github.com/wannier-developers/wannier90/tree/v3.1.0/src
Suggested meshes and broadenings need convergence tests. No material-specific
Fermi energy, transport lifetime, or energy limits are guessed here.
"""
from dataclasses import dataclass
import math
import re
from collections.abc import Mapping
from .wannier_paths import normalize_path


@dataclass(frozen=True)
class Profile:
    win_lines: tuple[str, ...]
    pw2_flags: dict[str, bool]
    warnings: tuple[str, ...]


DIRECTIONS = (
    dict(id='electronic',label='精细电子结构',tasks=('bands','qe_bands','dos','projected_dos','fermi_surface')),
    dict(id='local',label='局域轨道与模型',tasks=('orbitals','centres','model')),
    dict(id='transport',label='热电与电子输运',tasks=('boltzmann',)),
    dict(id='berry',label='Berry 曲率与霍尔响应',tasks=('berry_path','berry_slice','ahc','shc')),
    dict(id='optical',label='光学与非线性响应',tasks=('optical','shift_current')),
    dict(id='gyrotropic',label='轨道磁性与旋光',tasks=('orbital_magnetization','natural_optical_activity','current_induced_optical','current_induced_magnetization')),
)
_LABELS = ('插值能带','QE 能带对照','DOS','Wannier 轨道投影 DOS','费米面',
           'Wannier 轨道图','中心与展宽','在位能和跃迁矩阵','Seebeck / 电导率 / 电子热导率',
           'Berry 曲率路径','Berry 曲率切片','内禀反常霍尔','内禀自旋霍尔',
           '复光电导及磁光相关分量','位移电流','轨道磁化','自然旋光带间响应',
           '电流诱导旋光响应','电流诱导磁化响应')
TASKS = {task:dict(label=label,direction=direction['id'])
         for (task,direction),label in zip(((t,d) for d in DIRECTIONS for t in d['tasks']),_LABELS)}
FIELDS = {}


def _field(key,label,kind,tasks,unit='',default=None,required=False,**constraints):
    FIELDS[key] = dict(label=label,type=kind,unit=unit,default=default,
                       required=required,tasks=tuple(tasks.split()),**constraints)


_PATH = 'bands qe_bands berry_path shift_current'
_DOS = 'dos projected_dos'
_BERRY = 'ahc shc optical shift_current orbital_magnetization'
_GYRO = 'natural_optical_activity current_induced_optical current_induced_magnetization'
_FERMI = 'fermi_surface berry_path berry_slice ' + _BERRY + ' ' + _GYRO
_field('fermi_energy','费米能（QE 本征值能量零点）','float',_FERMI,'eV',required=True)
_field('kpoint_path','原 SCF 倒格基底路径','path',_PATH,required=True)
_field('bands_num_points','能带路径采样','int','bands qe_bands shift_current',default=100,min=2)
_field('kpath_num_points','Berry 路径采样','int','berry_path',default=100,min=2)
for key,label in [('dos_energy_min','DOS 能量下限'),('dos_energy_max','DOS 能量上限')]:
    _field(key,label,'float',_DOS,'eV',required=True)
_field('dos_energy_step','DOS 能量步长','float',_DOS,'eV',default=.01,positive=True)
_field('dos_smr_fixed_en_width','DOS 固定展宽（需收敛）','float',_DOS,'eV',default=.05,positive=True)
_field('dos_kmesh','DOS 积分网格（需收敛）','mesh',_DOS,default=(40,40,40))
_field('dos_project','投影 Wannier 轨道编号','int_list','projected_dos',required=True)
_field('fermi_surface_num_points','费米面每轴网格（需收敛）','int','fermi_surface',default=50,min=2)
_field('wannier_plot_list','绘图 Wannier 轨道编号','int_list','orbitals',required=True)
_field('wannier_plot_supercell','轨道图超胞','mesh','orbitals',default=(2,2,2))
_field('wannier_plot_format','轨道图格式','choice','orbitals',default='cube',choices=('cube','xsf'))
_field('wannier_plot_radius','轨道图半径（cube 需检查 FFT 覆盖）','float','orbitals','Å',default=3.5,positive=True)
_field('wannier_plot_spinor_mode','Spinor 图：总幅值/分量','choice','orbitals',default='total',choices=('total','up','down'))
_field('boltz_kmesh','BoltzWann 网格（需收敛）','mesh','boltzmann',default=(40,40,40))
for key,label,unit,positive in [('boltz_mu_min','化学势下限','eV',False),('boltz_mu_max','化学势上限','eV',False),
                             ('boltz_temp_min','温度下限','K',True),('boltz_temp_max','温度上限','K',True),
                             ('boltz_relax_time','常数弛豫时间','fs',True)]:
    _field(key,label,'float','boltzmann',unit,required=True,positive=positive)
_field('boltz_mu_step','化学势步长','float','boltzmann','eV',default=.01,positive=True)
_field('boltz_temp_step','温度步长','float','boltzmann','K',default=10.,positive=True)
_field('boltz_tdf_energy_step','输运分布能量步长（需收敛）','float','boltzmann','eV',default=.001,positive=True)
_field('boltz_2d_dir','二维体系法向（no 表示三维）','choice','boltzmann',default='no',choices=('no','x','y','z'))
_field('kslice_corner','切片原点','vector','berry_slice','倒格分数坐标',required=True)
_field('kslice_b1','切片第一边','vector','berry_slice','倒格分数坐标',required=True)
_field('kslice_b2','切片第二边','vector','berry_slice','倒格分数坐标',required=True)
_field('kslice_2dkmesh','切片网格（需收敛）','mesh2','berry_slice',default=(100,100))
_field('berry_kmesh','Berry 积分网格（需收敛）','mesh',_BERRY,default=(40,40,40))
for key,label,default in [('shc_alpha','自旋流方向',1),('shc_beta','电场方向',2),('shc_gamma','自旋极化方向',3)]:
    _field(key,label,'int','shc',default=default,min=1,max=3)
_field('shc_freq_scan','SHC 有限频率扫描','bool','shc',default=False)
_field('kubo_freq_min','光子能量下限','float','optical shift_current shc','eV',default=0.,min=0)
_field('kubo_freq_max','光子能量上限','float','optical shift_current shc','eV',positive=True)
_field('kubo_freq_step','光子能量步长','float','optical shift_current shc','eV',default=.01,positive=True)
_field('kubo_smr_fixed_en_width','响应展宽（需收敛）','float','optical shift_current shc','eV',default=.05,positive=True)
_field('kubo_eigval_max','参与响应的本征值能量上限','float','optical shift_current shc','eV')
_field('sc_eta','位移电流 eta（需收敛）','float','shift_current','eV',default=.04,positive=True)
_field('sc_phase_conv','位移电流相位约定','int','shift_current',default=1,min=1,max=2)
_field('gyrotropic_kmesh','旋光积分网格（需收敛）','mesh',_GYRO,default=(40,40,40))
_field('gyrotropic_freq_min','旋光光子能量下限','float','natural_optical_activity current_induced_optical','eV',default=0.,min=0)
_field('gyrotropic_freq_max','旋光光子能量上限','float','natural_optical_activity current_induced_optical','eV',required=True,positive=True)
_field('gyrotropic_freq_step','旋光光子能量步长','float','natural_optical_activity current_induced_optical','eV',default=.01,positive=True)
_field('gyrotropic_smr_fixed_en_width','旋光展宽（需收敛）','float',_GYRO,'eV',default=.05,positive=True)
_field('gyrotropic_eigval_max','旋光本征值能量上限（可选）','float',_GYRO,'eV')
_field('include_spin','旋光/磁化响应包含自旋项','bool','natural_optical_activity current_induced_magnetization',default=False)
_field('sc_w_thr','位移电流谱线尾部截断倍数','float','shift_current',default=5.,positive=True)
_field('kubo_smr_type','响应谱线展宽形式','choice','shift_current',default='gauss',
       choices=('gauss','cold','m-v','f-d','m-p1','m-p2'))
_field('kubo_adpt_smr','自适应响应展宽','bool','shift_current',default=False)
_field('kubo_adpt_smr_fac','自适应展宽系数','float','shift_current',default=math.sqrt(2),positive=True)
_field('kubo_adpt_smr_max','自适应展宽上限','float','shift_current','eV',default=1.,positive=True)

PROFILE_BLOCKS = frozenset({'kpoint_path'})
PROFILE_KEYS = frozenset(set(FIELDS)-PROFILE_BLOCKS-{'include_spin'} | {
    'bands_plot','dos','dos_adpt_smr','fermi_surface_plot','wannier_plot','wannier_plot_spinor_phase',
    'write_xyz','write_hr','boltzwann','kpath','kpath_task','kslice','kslice_task',
    'berry','berry_task','kubo_adpt_smr','kubo_smr_type','sc_w_thr',
    'bands_plot_format','gyrotropic','gyrotropic_task','num_elec_per_state'})


def fields_for_tasks(tasks):
    tasks = _tasks(tasks)
    fields = {key:dict(field) for key,field in FIELDS.items() if set(field['tasks']) & set(tasks)}
    if 'shift_current' in tasks:
        fields['kpoint_path']['default'] = 'auto'
        for key in ('kubo_freq_max', 'kubo_eigval_max'):
            fields[key]['required'] = True
        fields['kubo_freq_step']['default'] = .03
        fields['sc_phase_conv']['default'] = 2
    return fields


def _tasks(tasks):
    if isinstance(tasks,str) or not tasks:
        raise ValueError('tasks must be a nonempty list of task IDs')
    result = tuple(dict.fromkeys(tasks))
    unknown = set(result) - TASKS.keys()
    if unknown:
        raise ValueError('unknown Wannier task: ' + ', '.join(sorted(unknown)))
    return result


def _number(value,key,integer=False):
    if isinstance(value,bool):
        raise ValueError(f'{key} must be numeric, not boolean')
    try:
        result = float(str(value).replace('d','e').replace('D','e'))
    except (ValueError,TypeError) as exc:
        raise ValueError(f'{key} must be numeric') from exc
    if not math.isfinite(result) or (integer and result != int(result)):
        raise ValueError(f'{key} must be a finite ' + ('integer' if integer else 'number'))
    return int(result) if integer else result


def _validate(value,key,field):
    kind = field['type']
    if kind in ('float','int'):
        result = _number(value,key,kind=='int')
        if field.get('positive') and result <= 0 or 'min' in field and result < field['min'] or 'max' in field and result > field['max']:
            raise ValueError(f'{key} is outside its allowed range')
        return result
    if kind == 'bool':
        if not isinstance(value,bool):
            raise ValueError(f'{key} must be boolean')
        return value
    if kind == 'choice':
        if key == 'kubo_smr_type' and isinstance(value, str):
            value = value.lower()
            if re.fullmatch(r'm-p\d+', value):
                return value
        if value not in field['choices']:
            raise ValueError(f'{key} must be one of {field["choices"]}')
        return value
    if kind == 'path':
        return normalize_path(value)
    if isinstance(value,str):
        if kind == 'int_list':
            expanded = []
            for part in re.split(r'[,;\s]+',value.strip()):
                match = re.fullmatch(r'(\d+)[-:](\d+)',part)
                if match:
                    start,end = map(int,match.groups())
                    if end < start or end-start > 100000:
                        raise ValueError(f'{key} has an invalid range')
                    expanded.extend(range(start,end+1))
                else:
                    expanded.append(part)
            value = expanded
        else:
            value = value.replace(',',' ').split()
    try:
        result = tuple(_number(v,key,kind!='vector') for v in value)
    except TypeError as exc:
        raise ValueError(f'{key} must be a list') from exc
    if kind in ('mesh','mesh2','vector') and len(result) != (2 if kind=='mesh2' else 3):
        raise ValueError(f'{key} has the wrong number of components')
    if kind != 'vector' and (not result or any(v < 1 for v in result)):
        raise ValueError(f'{key} requires positive integers')
    if kind == 'int_list':
        result = tuple(dict.fromkeys(result))
    return result


def _format(value):
    if isinstance(value,bool): return 'true' if value else 'false'
    if isinstance(value,float): return f'{value:.12g}'
    if isinstance(value,(tuple,list)): return ' '.join(_format(v) for v in value)
    return str(value)


def render_profile(tasks,parameters,spin_mode,version='3.1.0', *, defer_fermi=False,
                   defer_response=()):
    """Render only selected tasks; union operator dependencies, never run tools.

    ``num_wann`` may be supplied as validation context to bound orbital lists.
    Other parameters use official .win names except the UI-only include_spin.
    """
    if version != '3.1.0':
        raise ValueError(f'unsupported Wannier90 version {version}; verified target is 3.1.0')
    tasks = _tasks(tasks)
    if not isinstance(parameters,Mapping):
        raise ValueError('parameters must be a mapping')
    if defer_fermi:
        from .wannier_output_defaults import midgap_allowed
        if not midgap_allowed({'tasks': tasks}) or parameters.get('fermi_energy') is not None:
            raise ValueError('Only an unresolved shift-current occupation reference may be deferred')
    if (set(defer_response) - {'kubo_freq_max', 'kubo_eigval_max'}
            or defer_response and 'shift_current' not in tasks):
        raise ValueError('Only shift-current response energy limits may be deferred')
    unknown = set(parameters) - FIELDS.keys() - {'num_wann'}
    if unknown:
        raise ValueError('unsupported Wannier90 3.1.0 parameter(s): ' + ', '.join(sorted(unknown)))
    if spin_mode not in ('scalar','nonmagnetic','none','collinear','up','down','spinor','noncollinear'):
        raise ValueError('unknown spin_mode')
    spinor = spin_mode in ('spinor','noncollinear')
    values = {}
    for key,field in fields_for_tasks(tasks).items():
        # Static SHC uses broadening/upper eigenvalue limit, not a frequency range.
        if key.startswith('kubo_freq_') and set(tasks).isdisjoint({'optical','shift_current'}) and not parameters.get('shc_freq_scan',False):
            continue
        value = parameters.get(key,field['default'])
        if value is None:
            if key == 'fermi_energy' and defer_fermi or key in defer_response:
                continue
            if field['required']:
                raise ValueError(f'{key} is required for the selected task')
            continue
        values[key] = _validate(value,key,field)
    if ('shc' in tasks or values.get('include_spin')) and not spinor:
        raise ValueError('spin matrices require a spinor SCF source; changing NSCF spin flags cannot provide it')
    if values.get('kubo_freq_min', 0) != 0 and 'kubo_freq_max' not in values and 'kubo_freq_max' not in defer_response:
        raise ValueError('kubo_freq_max 必须明确填写：光子能量下限已改为非零值，不能保证程序默认上限大于该下限。')
    for lower,upper,allow_equal in [('dos_energy_min','dos_energy_max',False),
                                   ('boltz_mu_min','boltz_mu_max',True),('boltz_temp_min','boltz_temp_max',True),
                                   ('kubo_freq_min','kubo_freq_max',False),('gyrotropic_freq_min','gyrotropic_freq_max',False)]:
        if lower in values and upper in values and (values[upper] < values[lower] or not allow_equal and values[upper] == values[lower]):
            raise ValueError(f'{upper} must be greater than ' + ('or equal to ' if allow_equal else '') + lower)
    if 'berry_slice' in tasks:
        a,b = values['kslice_b1'],values['kslice_b2']
        cross = (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
        if sum(v*v for v in cross) < 1e-24:
            raise ValueError('kslice_b1 and kslice_b2 must span a nonzero plane')
    if 'num_wann' in parameters:
        num_wann = _number(parameters['num_wann'],'num_wann',True)
        if num_wann < 1: raise ValueError('num_wann must be positive')
        for key in ('dos_project','wannier_plot_list'):
            if key in values and max(values[key]) > num_wann:
                raise ValueError(f'{key} exceeds num_wann')
    options = {'num_elec_per_state':2 if spin_mode in ('scalar','nonmagnetic','none') else 1}
    flags = {'write_amn':True,'write_mmn':True}
    warnings = ['Integration meshes, path sampling and broadenings are suggestions and require convergence tests.']
    if set(tasks)&{'bands','qe_bands'}: options['bands_plot'] = True
    if 'shift_current' in tasks:
        options.update(bands_plot=True, bands_plot_format='gnuplot')
        flags['write_unk'] = False
    if set(tasks)&{'dos','projected_dos'}: options.update(dos=True,dos_adpt_smr=False)
    if 'fermi_surface' in tasks: options['fermi_surface_plot'] = True
    if 'orbitals' in tasks:
        options['wannier_plot'] = True
        flags['write_unk'] = True
        if values['wannier_plot_format'] == 'cube':
            warnings.append('cube coverage depends on the final Wannier centres and available FFT points and cannot be guaranteed before localization. If plotting fails, increase wannier_plot_supercell, decrease wannier_plot_radius, or choose xsf.')
        if spinor:
            options['wannier_plot_spinor_phase'] = False
            warnings.append('spinor orbital plots show amplitude for the chosen total/component mode, not the sign of a real scalar orbital.')
    if 'centres' in tasks:
        options['write_xyz'] = True
        warnings.append('Wannier centres and spreads are reported in .wout; centres also appear in the exported XYZ.')
    if 'model' in tasks: options['write_hr'] = True
    if 'boltzmann' in tasks:
        options['boltzwann'] = True
        warnings.append('BoltzWann uses the specified constant relaxation time in fs and outputs Seebeck S, conductivity σ and thermal coefficient K in kappa.dat. Obtain open-circuit electronic thermal conductivity as κ_e = K − T Sᵀ σ S using consistent tensor conventions; lattice thermal conductivity is excluded.')
    if 'berry_path' in tasks: options.update(kpath=True,kpath_task='curv')
    if 'berry_slice' in tasks: options.update(kslice=True,kslice_task='curv')
    berry = [code for task,code in [('ahc','ahc'),('shc','shc'),('optical','kubo'),('shift_current','sc'),('orbital_magnetization','morb')] if task in tasks]
    if berry: options.update(berry=True,berry_task=' '.join(berry))
    if set(tasks)&{'shc','optical','shift_current'}: options['kubo_adpt_smr'] = False
    if 'shc' in tasks:
        flags['write_spn'] = True
        warnings.append('Official Wannier90 3.1.0 SHC uses its Qiao implementation; no shc_method/shc_ryoo keyword is written.')
    if 'orbital_magnetization' in tasks or 'current_induced_magnetization' in tasks: flags['write_uHu'] = True
    if set(tasks)&set(_GYRO.split()):
        gyro = ''
        if 'natural_optical_activity' in tasks: gyro += '-noa'
        if 'current_induced_optical' in tasks: gyro += '-dw'
        if 'current_induced_magnetization' in tasks: gyro += '-k'
        if values.get('include_spin'):
            gyro += '-spin'
            flags['write_spn'] = True
        if set(tasks)&{'current_induced_optical','current_induced_magnetization'}: gyro += '-c'
        options.update(gyrotropic=True,gyrotropic_task=gyro)
        warnings.append('Gyrotropic output contains response tensors; converting them to measured rotations or current-induced magnetization requires experimental geometry and driving conditions.')
    if 'optical' in tasks:
        warnings.append('The complex conductivity tensor includes magneto-optical components; it is not a complete Kerr/Faraday angle calculation.')
    path = values.pop('kpoint_path',None)
    values.pop('include_spin',None)
    if values.get('wannier_plot_format') == 'xsf':
        values['wannier_plot_format'] = 'xcrysden'
    if not spinor: values.pop('wannier_plot_spinor_mode',None)
    options.update(values)
    # Pending occupation data must not erase the requested calculation.
    # Keep its task switches; only EF is deferred until before postw90.
    lines = [f'{key} = {_format(value)}' for key,value in options.items()]
    if defer_fermi:
        lines.insert(0, '! QBOX: occupation reference pending; complete the NSCF step in README before response calculations.')
    for key in defer_response:
        lines.insert(0, f'! QBOX: {key} pending; explicitly set it before running postw90 (see README).')
    if path: lines.extend(['begin kpoint_path',*(segment.win_line() for segment in path),'end kpoint_path'])
    return Profile(tuple(lines),flags,tuple(warnings))
