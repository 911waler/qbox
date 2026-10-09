"""Display-only Chinese guidance for Wannier input fields.

This catalog supplies no defaults and changes no configuration. Examples are
syntax illustrations, never recommendations for a material. Scientific meanings
follow wannier_profiles/wannier_inputs and official Wannier90 v3.1.0 sources:
parameters.F90; plot.F90; postw90/{dos,kpath,berry,boltzwann,gyrotropic,wan_ham}.F90.
In particular, path sampling refers to the first segment, sc_eta regularizes
energy denominators, and BoltzWann's kappa.dat contains the raw K coefficient.
"""


def _entry(label, help_text, example, clear_effect):
    return {
        'label': label,
        'help': help_text,
        'example': '仅格式示例（非默认值，非材料参数推荐）：' + example,
        'clear_effect': clear_effect,
    }


_RESTORE = '清空后恢复菜单显示的模板默认值。'
_REQUIRED = '当前项目需要此项；未设置时不能生成，请按实际计算填写。'
_OUTER_CLEAR = '上下界同时清空后不写外窗，交由 Wannier90 默认处理；只清空一端或保留冻结窗会检查失败。'
_FROZEN_CLEAR = '上下界同时清空后不设置冻结窗；只清空一端会检查失败。'


FIELD_HELP = {
    # Shared model and source settings.
    'nbnd': _entry(
        'QE 每个自旋通道的能带数',
        '填写 NSCF 要计算的总带数，共线自旋的 up/down 各使用此数量。'
        '排除能带后仍须有足够的带容纳 num_wann；请依据已计算能带和目标能区确认。',
        '24（正整数）', '初次读取 SCF 时优先保留已有带数，缺失时按基组和电子容量给出首轮初值；手动清空后需重新填写。'),
    'num_wann': _entry(
        '模型中的 Wannier 轨道数',
        '填写最终模型的轨道数，它决定哈密顿量的维度。'
        '须与保留的展开投影数一致，且不超过排除能带后的可用带数。',
        '12（正整数）', '初值按投影展开数填写；修改投影后请同时核对本项，手动清空后需重新填写。'),
    'exclude_bands': _entry(
        '不参与 Wannier 化的 QE 能带',
        '填写要排除的原始 QE 能带编号，从 1 开始，例如明确不纳入模型的低能带。'
        '这些是能带编号，不是原子或 Wannier 轨道编号。',
        '1 2 3（空格分隔的编号）', '不设置或清空表示不排除任何 QE 能带。'),
    'select_projections': _entry(
        '从展开投影中保留的编号',
        '投影数多于目标轨道数时，填写实际展开后的投影编号，从 1 开始。'
        '编号按原子、轨道及自旋分量展开，选中数量必须恰好等于 num_wann。',
        '1 3 5（空格分隔的编号）',
        '不设置或清空表示使用全部展开投影；此时展开总数必须等于 num_wann。'),
    'projections': _entry(
        '初始投影轨道',
        '初值根据实际赝势所列的原子轨道类型生成；可改选原子类型或单个原子的 s、p、d、杂化轨道。'
        '按原子类型选择会作用于该类型的每个原子，旋量投影还会展开自旋分量。',
        'atom:1:s;p（语法示例，须按实际原子和轨道选择）',
        '清空后需要重新添加明确投影；不会使用随机轨道补齐。'),
    'num_iter': _entry(
        '局域化最大迭代次数',
        '填写最小化 Wannier 展宽的最大迭代次数；迭代尚未收敛时可调整。'
        '它不是收敛阈值，达到最大次数不代表已收敛。',
        '200（正整数）', '位移电流恢复模板上限 1000；其他任务不写此参数时使用 Wannier90 自身默认值。'),
    'conv_tol': _entry(
        '局域化展宽变化的收敛阈值',
        '填写相邻迭代的总展宽变化阈值，单位 Å²。'
        '连续 conv_window 步都满足阈值时才判为收敛；conv_window 大于 1 时启用检查。'
        '达到最大迭代次数不代表收敛。',
        '1.0d-9（Å²，非负数）', '清空后恢复位移电流模板的收敛阈值。'),
    'conv_window': _entry(
        '局域化收敛检查的连续步数',
        '填写需要连续满足 conv_tol 的迭代步数。大于 1 时启用收敛检查；'
        '-1、0 或 1 关闭这项检查，迭代最多执行到 num_iter。',
        '5（整数；-1 或非负整数）', '清空后恢复位移电流模板的连续步数。'),
    'dis_num_iter': _entry(
        '解纠缠最大迭代次数',
        '可用能带多于目标轨道、需要选取平滑子空间时，限制解纠缠迭代次数。'
        '应结合 .wout 中的收敛记录判断，而不是只增加次数。',
        '300（正整数）', '位移电流恢复模板上限 1200；其他任务不写此参数时使用 Wannier90 自身默认值。'),
    'dis_mix_ratio': _entry(
        '解纠缠迭代的混合比例',
        '填写每步迭代中新子空间的混合比例，范围大于 0 且不超过 1。'
        '只在模型轨道数小于可用能带数、执行解纠缠时生效。',
        '0.5（0 < 数值 ≤ 1）', '清空后恢复位移电流模板的混合比例。'),
    'dis_conv_tol': _entry(
        '解纠缠的收敛阈值',
        '填写规范不变展宽的相对变化阈值。与 dis_conv_window 配合判断子空间是否收敛；'
        '这不是局域化阶段的 conv_tol。',
        '1.0d-9（非负数）', '清空后恢复位移电流模板的解纠缠收敛阈值。'),
    'dis_conv_window': _entry(
        '解纠缠收敛检查的连续步数',
        '填写用于判断解纠缠收敛的连续迭代步数，与 dis_conv_tol 配合使用。'
        '只在执行解纠缠时生效。',
        '3（正整数）', '清空后恢复位移电流模板的解纠缠连续步数。'),
    'seed': _entry(
        'Wannier 文件名前缀',
        '同一模型的 .win、.chk 和接口文件使用这个前缀，填写名称而非路径。'
        '已有模型须保留原前缀，避免与配套数据失配。',
        'sample_w90（不带 .win）', '新模型须有有效名称；已有模型固定使用原前缀。'),
    'grid': _entry(
        '建立模型的均匀 k 点网格',
        '填写三个正整数，生成包含 Gamma 点的完整 NSCF 网格及匹配的 Wannier k 点。'
        '这是建立模型用的粗网格，后处理积分网格另行设置。',
        '6 6 4', '清空后需重新填写完整网格；不会自动确定已收敛网格。'),
    'source': _entry(
        '结构或模型来源文件',
        '新模型可选择 CIF 或 QE SCF 输入；CIF 会先衔接 SCF 输入配置。'
        '已有模型选择配套数据所在目录的 .win。',
        '/work/project/scf.in（也可填写 CIF 或 .win 路径）',
        '必须选定来源才能生成；路径输入处回车保留现有来源。'),
    'source_output': _entry(
        '辅助读取参数的 SCF/NSCF 输出',
        '自动查找当前目录、原 SCF 所在目录和 QE 运行目录中，已完成且与来源匹配的 SCF/NSCF 输出。'
        '找到一份时直接读取，多份时由您选择；也可填写路径，在生成前验证。'
        '明确填写的值优先；带数和本征值范围不会改动基组或能窗。'
        '中性 fixed 占据的完整 NSCF 网格若含空带且存在带隙，可为位移电流提供带隙中点占据参考。',
        '/work/project/scf.out 或 /work/project/nscf.out',
        '输入 - 禁用读取并移除自动导入值，保留手动值；输入 a 可重新识别。'),
    'run_root': _entry(
        '原 QE 计算的运行目录',
        '填写原来执行 QE 时的工作目录，用它解释 SCF 输入中相对的 outdir、pseudo_dir 和 wfcdir。'
        '它不一定是 SCF 输入文件所在目录。',
        '/work/project/run', '清空后按当前工作目录解释相对路径，请确认能定位同一套 QE 数据。'),
    'reference_source': _entry(
        '已有模型对应的原 SCF 输入',
        '选择建立该 Wannier 模型的原 SCF 输入，用于识别匹配的 SCF/NSCF 输出。'
        '生成 QE 能带对照时也需要此文件，以保留相同结构、赝势、磁性和其他物理设置。',
        '/work/project/scf.in', '未提供时不能自动识别 QE 输出；已有模型的 QE 能带对照必须提供。'),
    'band_kpt': _entry(
        'Wannier 实际能带采样点文件',
        '填写 Wannier90 输出的 seed_band.kpt，使 QE 逐点使用同一组实际 k 坐标。'
        '需要严格逐点比较能带时使用。',
        '/work/project/sample_band.kpt',
        '不设置或清空后按所选高对称路径生成 QE 采样；不保证与 Wannier 实际输出逐点相同。'),
    'version': _entry(
        '目标 Wannier90 版本',
        '选择生成输入所依据的版本；当前参数已按官方 3.1.0 核实。'
        '它不会安装或切换计算程序。',
        '3.1.0', '当前仅支持菜单列出的已验证版本，保留现有选择即可。'),
    'mode': _entry(
        '从哪里开始这次任务',
        '首次建立或修改轨道、能窗时选择新模型；已经完成 Wannier 化时可选已有模型做后处理。'
        '已有模型方式保持原轨道、网格和能窗。',
        'new / existing（在菜单中选择对应编号）', '保留当前方式；切换后须选择与方式匹配的来源文件。'),
    'reference': _entry(
        '能窗数值的能量参考',
        'absolute 表示与 QE 本征值共用能量零点；fermi 表示填写相对费米能的偏移。'
        '选择 fermi 后，生成时会将明确的费米能加回各能窗边界。',
        'absolute / fermi（在菜单中选择对应编号）', '清空后使用 absolute，即 QE 本征值能量零点。'),
    'windows_fermi_energy': _entry(
        '换算相对能窗所用的费米能',
        '相对费米能填写能窗时，另提供费米能在 QE 本征值零点下的数值，单位 eV。'
        '此值用于平移能窗，不能填写成相对自身的 0。',
        '5.2（eV，须替换为同一次计算的已知值）',
        '选择相对能窗时须明确填写费米能，不能清空；输入 b 可取消本次能量参考修改。'),
    'dis_win_min': _entry(
        '解纠缠外窗下界',
        '填写允许参与解纠缠的能带范围下界，单位 eV，按所选能量参考填写。'
        '须与上界成对，每个 k 点外窗内都应有至少 num_wann 条可用能带。',
        '-8.0（eV）', _OUTER_CLEAR),
    'dis_win_max': _entry(
        '解纠缠外窗上界',
        '填写参与解纠缠的能带范围上界，单位 eV，按所选能量参考填写。'
        '应覆盖目标能区，并通过实际 .eig 核对各 k 点的带数。',
        '9.0（eV）', _OUTER_CLEAR),
    'dis_froz_min': _entry(
        '冻结窗下界',
        '需要强制保留某段原始能带时设置冻结窗下界，单位 eV。'
        '冻结窗须位于外窗内，且每个 k 点冻结的带数不能超过 num_wann。',
        '-3.0（eV）', _FROZEN_CLEAR),
    'dis_froz_max': _entry(
        '冻结窗上界',
        '填写要在解纠缠中强制保留的能区上界，单位 eV。'
        '与冻结窗下界成对设置；范围越大并不一定得到更好的模型。',
        '2.5（eV）', _FROZEN_CLEAR),

    # Electronic structure and real-space outputs.
    'fermi_energy': _entry(
        '后处理采用的费米能',
        '填写与 QE 本征值共用能量零点的费米能，单位 eV，用于占据判断和费米面等响应。'
        '可从菜单 2 识别的 SCF/NSCF 输出读取，手动填写的值优先。'
        '绝缘体使用 occupations=fixed 是合法设置，无需为了打印费米能而改成展宽占据。'
        '位移电流可先生成 SCF/NSCF 输入；中性 fixed 体系的完整网格含空带且有带隙时，'
        '可用带隙中点估计作占据参考，它不是实际化学势，也不能直接用于其他需真实费米能的响应。'
        '若为模拟掺杂而改变此值，应明确这是刚性能带假设。',
        '5.2（eV，须替换为实际选定值）',
        '手动清空后不会再自动补入；位移电流可先生成准备输入，其他需费米能的项目须填写可靠值。'),
    'kpoint_path': _entry(
        '能带或 Berry 曲率的 k 路径',
        '每段填写两个点的标签和倒格分数坐标，基底必须与原 SCF 晶胞一致。'
        '也可选择原晶胞自动路径；不连续的路径段会保持断开。',
        'G 0 0 0 X 0.5 0 0（两个标签、六个坐标）',
        '这些路径任务需要明确路径；自动生成也需主动选择，空路径不能生成。'),
    'bands_num_points': _entry(
        '能带路径的采样密度',
        '填写 Wannier 能带路径第一段的分段数，其他段按长度调整采样。'
        '增加它可使曲线更细，但不能改善已有模型本身的精度。',
        '120（整数，至少 2）', _RESTORE),
    'kpath_num_points': _entry(
        'Berry 路径的采样密度',
        '填写 Berry 曲率路径第一段的分段数，其他段按长度调整。'
        '曲率尖峰附近可能需要更密采样。',
        '160（整数，至少 2）', _RESTORE),
    'dos_energy_min': _entry(
        'DOS 能量范围下限',
        '填写 DOS 输出能量轴的下限，单位 eV，与 QE 本征值共用能量零点。'
        '这个范围不会扩大 Wannier 模型已包含的能带。',
        '-7.0（eV）', _REQUIRED),
    'dos_energy_max': _entry(
        'DOS 能量范围上限',
        '填写 DOS 输出能量轴的上限，单位 eV，须高于下限。'
        '选择范围前应检查模型对该能区的插值质量。',
        '8.0（eV）', _REQUIRED),
    'dos_energy_step': _entry(
        'DOS 能量采样步长',
        '填写 DOS 能量轴相邻采样点的间隔，单位 eV。'
        '较小步长细化输出曲线，仍须结合积分网格和展宽测试。',
        '0.02（eV，正数）', _RESTORE),
    'dos_smr_fixed_en_width': _entry(
        'DOS 固定能量展宽',
        '填写将离散能级平滑为 DOS 的固定展宽，单位 eV。'
        '本模板关闭自适应展宽，此值应与积分网格一起做收敛测试。',
        '0.08（eV，正数）', _RESTORE),
    'dos_kmesh': _entry(
        'DOS 积分网格',
        '填写三个正整数，指定用插值能带计算 DOS 的布里渊区网格。'
        '它不改变建立 Wannier 模型时的 NSCF 网格。',
        '60 60 30', _RESTORE),
    'dos_project': _entry(
        '投影 DOS 的 Wannier 轨道编号',
        '填写要投影到的模型轨道编号，从 1 到 num_wann。'
        '这里投影到 Wannier 轨道，不是 QE 原子投影 DOS 的原子编号。',
        '1 2 5', _REQUIRED),
    'fermi_surface_num_points': _entry(
        '费米面三维采样密度',
        '填写每个倒格方向的采样数，用于生成 BXSF 能量网格。'
        '需要模型在所选费米能附近可靠，且存在穿越该能量的能带。',
        '72（整数，至少 2）', _RESTORE),
    'wannier_plot_list': _entry(
        '要绘制的 Wannier 轨道',
        '填写模型轨道编号，从 1 到 num_wann，程序只导出这些轨道的空间体数据。'
        '绘图需要同一次计算的 UNK 波函数文件。',
        '1 4 7', _REQUIRED),
    'wannier_plot_supercell': _entry(
        '轨道绘图覆盖的超胞',
        '填写沿三个晶格方向展开的晶胞数，扩大空间绘图覆盖范围。'
        'Cube 半径超出可用 FFT 点覆盖时，可增大此项或缩小绘图半径。',
        '4 4 3', _RESTORE + '默认超胞不保证覆盖最终轨道中心附近的全部绘图区域。'),
    'wannier_plot_format': _entry(
        '轨道体数据格式',
        '选择 cube 或 xsf，按后续可视化软件支持的格式输出。'
        'Cube 还需满足绘图半径与 FFT 覆盖范围的要求。',
        'cube / xsf（在菜单中选择对应编号）', _RESTORE),
    'wannier_plot_radius': _entry(
        'Cube 绘图半径',
        '填写以 Wannier 中心为参考的绘图半径，单位 Å，主要用于 Cube 输出。'
        '半径增大时也要检查超胞和可用 FFT 网格能否覆盖。',
        '2.8（Å，正数）', _RESTORE),
    'wannier_plot_spinor_mode': _entry(
        'Spinor 轨道显示的分量',
        'total 显示总幅值，up/down 显示相应自旋分量的幅值。'
        '仅适用于 spinor 模型，不能按实标量轨道正负号解读。',
        'total / up / down（在菜单中选择对应编号）', _RESTORE),

    # BoltzWann. Chemical potentials retain the QE energy zero.
    'boltz_kmesh': _entry(
        '电子输运积分网格',
        '填写三个正整数，用插值能带在此网格上计算输运分布。'
        '费米能附近的细小能带结构可能需要较密网格。',
        '64 64 32', _RESTORE),
    'boltz_mu_min': _entry(
        '化学势扫描下限',
        '填写扫描起点，单位 eV，与 QE 本征值共用能量零点。'
        '扫描改变占据的化学势，不会重新自洽计算掺杂结构。',
        '4.0（eV）', _REQUIRED),
    'boltz_mu_max': _entry(
        '化学势扫描上限',
        '填写扫描终点，单位 eV，须不低于下限。'
        '上下限相同可只计算一个化学势。',
        '4.6（eV）', _REQUIRED),
    'boltz_mu_step': _entry(
        '化学势扫描步长',
        '填写相邻化学势点之间的间隔，单位 eV。'
        '较小间隔可细查载流子占据变化，但不等于给定了实际掺杂浓度。',
        '0.025（eV，正数）', _RESTORE),
    'boltz_temp_min': _entry(
        '温度扫描下限',
        '填写温度扫描起点，单位 K，必须大于 0。'
        '温度影响电子占据，不会加入晶格热导。',
        '250（K）', _REQUIRED),
    'boltz_temp_max': _entry(
        '温度扫描上限',
        '填写温度扫描终点，单位 K，须不低于下限。'
        '上下限相同可只计算一个温度。',
        '450（K）', _REQUIRED),
    'boltz_temp_step': _entry(
        '温度扫描步长',
        '填写相邻温度点之间的间隔，单位 K，须为正数。'
        '它只控制采样，不代表散射过程的温度依赖。',
        '25（K）', _RESTORE),
    'boltz_relax_time': _entry(
        '电子的常数弛豫时间',
        '填写输运计算假设的弛豫时间，单位 fs；电导率和热输运幅度会依赖它。'
        '需要实验、其他计算或明确模型假设作为依据，程序不会由能带推算。',
        '15（fs，须有实际依据）', _REQUIRED),
    'boltz_tdf_energy_step': _entry(
        '输运分布函数的能量步长',
        '填写构建输运分布函数时的能量网格间隔，单位 eV。'
        '这是内部能量积分的分辨率，与输出化学势步长分开设置。',
        '0.002（eV，正数）', _RESTORE),
    'boltz_2d_dir': _entry(
        '二维 Seebeck 计算的非周期方向',
        '三维体材料选择 no；二维体系按笛卡尔非周期方向选择 x、y 或 z。'
        '此项采用二维 Seebeck 求解，不会自动把含真空晶胞的电导率换算成片电导。',
        'no / x / y / z（在菜单中选择对应编号）', _RESTORE),

    # Berry, Hall and optical responses.
    'kslice_corner': _entry(
        'Berry 切片的起点',
        '填写切片平行四边形的一个角点，使用原 SCF 倒格基底的分数坐标。'
        '与两条边向量共同决定所取的平面。',
        '-0.5 -0.5 0', _REQUIRED),
    'kslice_b1': _entry(
        'Berry 切片的第一条边向量',
        '填写从切片起点出发的第一条边向量，使用倒格分数坐标。'
        '填写的是位移向量，不是另一端的绝对坐标。',
        '1 0 0', _REQUIRED),
    'kslice_b2': _entry(
        'Berry 切片的第二条边向量',
        '填写从切片起点出发的第二条边向量，使用倒格分数坐标。'
        '两条边须非零且不共线，才能确定有效切片。',
        '0 1 0', _REQUIRED),
    'kslice_2dkmesh': _entry(
        'Berry 切片二维网格',
        '填写沿切片两条边采样的两个正整数。'
        '增加采样可分辨局部曲率峰，但不会改善原模型。',
        '160 120', _RESTORE),
    'berry_kmesh': _entry(
        'Berry 与光学响应积分网格',
        '填写三个正整数，控制霍尔、光学、位移电流或轨道磁化的布里渊区积分。'
        '避免仅凭曲线平滑判断收敛，应检查网格加密后的响应变化。',
        '64 64 48', _RESTORE),
    'shc_alpha': _entry(
        '自旋流的空间流动方向',
        '选择自旋流流向的笛卡尔轴：1=x、2=y、3=z。'
        '它与电场方向、自旋极化方向共同指定一个自旋霍尔张量分量。',
        '1（x；也可选 2=y 或 3=z）', _RESTORE),
    'shc_beta': _entry(
        '驱动自旋霍尔响应的电场方向',
        '选择外加电场的笛卡尔轴：1=x、2=y、3=z。'
        '这是张量的电场指标，与自旋流流向分开设置。',
        '2（y；也可选 1=x 或 3=z）', _RESTORE),
    'shc_gamma': _entry(
        '自旋流携带的自旋极化方向',
        '选择自旋极化的笛卡尔轴：1=x、2=y、3=z。'
        '此指标不改变原 SCF 的磁性或自旋轨道耦合设置。',
        '3（z；也可选 1=x 或 2=y）', _RESTORE),
    'shc_freq_scan': _entry(
        '是否扫描有限频率自旋霍尔响应',
        '需要频率依赖响应时开启，并填写光子能量范围。'
        '关闭时按所选费米能计算静态自旋霍尔响应。',
        'yes / no（在菜单中选择是或否）', _RESTORE),
    'kubo_freq_min': _entry(
        '响应谱的光子能量下限',
        '填写扫描起点，单位是光子能量 eV，而非 Hz。'
        '适用于光电导、位移电流，以及开启频率扫描的自旋霍尔响应。',
        '0.1（eV，非负数）', _RESTORE),
    'kubo_freq_max': _entry(
        '响应谱的光子能量上限',
        '填写扫描终点，单位 eV，须大于下限。'
        '初值为冻结窗绝对上限减去后处理参考能；例如参考能上方 10 eV 对应光子上限 10 eV。'
        '可手动修改，修改或清空后不再自动更新。',
        '3.5（eV）', '位移电流须在运行 postw90 前补全；其他响应下限为零时可用运行时默认值；静态 SHC 不使用此项。'),
    'kubo_freq_step': _entry(
        '响应谱的光子能量步长',
        '填写频谱相邻采样点的目标间隔，单位 eV。'
        '采样步长和响应展宽共同影响谱线分辨率，应分别检查。',
        '0.025（eV，正数）', _RESTORE),
    'kubo_smr_fixed_en_width': _entry(
        '光学或自旋霍尔响应的固定展宽',
        '填写响应能量分母或跃迁谱线使用的固定展宽，单位 eV。'
        '模板初始关闭自适应展宽；关闭时使用此固定宽度，应结合 k 网格检验结果对展宽的依赖。',
        '0.06（eV，正数）', _RESTORE),
    'kubo_eigval_max': _entry(
        '响应跃迁初态和末态上限（QE 零点）',
        '初值取冻结窗的绝对上限，单位 eV，与 QE 本征值共用零点；相对能窗先换算。'
        '此初值不依赖费米能，负的绝对上限也合法。'
        '可手动修改，修改或清空后不再自动更新；它不限制虚中间态求和。',
        '12.0（eV）', '清空后不再自动补入；位移电流在运行 postw90 前需补全，其他响应可用运行时默认值。'),
    'sc_eta': _entry(
        '位移电流近简并分母的正则化参数',
        '填写处理能带接近简并时能量分母的 eta，单位 eV。'
        '它与频谱展宽分别设置；过大或过小均须通过收敛检查判断。',
        '0.03（eV，正数）', _RESTORE),
    'sc_phase_conv': _entry(
        '位移电流计算的相位约定',
        '1 为紧束缚约定，在傅里叶相位中纳入 Wannier 中心；2 为 Wannier90 约定。'
        '这是计算表达式的相位约定，不是正负号显示或 SOC 开关。',
        '1 或 2', _RESTORE),
    'sc_w_thr': _entry(
        '位移电流谱线尾部截断范围',
        '填写谱线尾部截断相对于当前展宽的倍数，无量纲。'
        '它控制偏离共振能量较远的谱线贡献，不是跃迁强度阈值。',
        '5.0（正数，展宽的倍数）', _RESTORE),
    'kubo_smr_type': _entry(
        '响应谱线的展宽函数',
        '选择跃迁谱线的展宽函数。模板使用 Gaussian；其他选项保留用于已有模型或有明确依据的设置。'
        '改变函数后须重新检查展宽和积分网格对光谱的影响。',
        'gauss（Gaussian）', _RESTORE),
    'kubo_adpt_smr': _entry(
        '是否使用自适应展宽',
        '关闭时使用固定展宽；开启时按局部能带变化和 k 点间距调整展宽，'
        '并受自适应比例和最大展宽限制。模板初始关闭。',
        'no（在菜单中选择是或否）', _RESTORE),
    'kubo_adpt_smr_fac': _entry(
        '自适应展宽的比例系数',
        '填写自适应展宽的无量纲比例系数。仅在开启自适应展宽时生效。',
        '1.4（正数）', _RESTORE),
    'kubo_adpt_smr_max': _entry(
        '自适应展宽的上限',
        '填写允许的最大自适应展宽，单位 eV。仅在开启自适应展宽时生效；'
        '它不是响应频率范围或跃迁能量截止。',
        '1.0（eV，正数）', _RESTORE),

    # Gyrotropic response tensors.
    'gyrotropic_kmesh': _entry(
        '旋光与电流诱导响应积分网格',
        '填写三个正整数，对插值后的自然旋光或电流诱导响应做布里渊区积分。'
        '费米面附近及低频响应可能对网格较敏感。',
        '72 72 48', _RESTORE),
    'gyrotropic_freq_min': _entry(
        '旋光响应的光子能量下限',
        '填写自然旋光或电流诱导光学响应的扫描起点，单位 eV。'
        '低频极限可能较敏感，应结合展宽检查。',
        '0.02（eV，非负数）', _RESTORE),
    'gyrotropic_freq_max': _entry(
        '旋光响应的光子能量上限',
        '填写光子能量扫描终点，单位 eV，须大于下限。'
        '输出是响应张量，转换为测量旋转角还需要实验几何等条件。',
        '0.8（eV）', _REQUIRED),
    'gyrotropic_freq_step': _entry(
        '旋光响应的光子能量步长',
        '填写光子能量采样的目标间隔，单位 eV。'
        '缩小间隔可细查频率变化，但不能替代展宽和 k 网格收敛。',
        '0.02（eV，正数）', _RESTORE),
    'gyrotropic_smr_fixed_en_width': _entry(
        '旋光计算的能量展宽',
        '填写旋光模块的固定能量展宽，单位 eV，涉及频率分母或费米面平滑处理。'
        '应检查响应对该值的依赖，尤其是低频和金属体系。',
        '0.04（eV，正数）', _RESTORE),
    'gyrotropic_eigval_max': _entry(
        '自然旋光求和的空带能量上限',
        '需要限制自然旋光带间求和的空带范围时，填写本征值上限，单位 eV。'
        '与 QE 本征值共用能量零点，不是光子能量上限。',
        '11.0（eV）',
        '不设置或清空后不写此项；Wannier90 根据冻结窗、可用本征值或外窗给出内部默认。'),
    'include_spin': _entry(
        '是否计入旋光或磁化的自旋贡献',
        '需要自然旋光或电流诱导磁化的自旋项时开启，要求同一 spinor 模型的 .spn 数据。'
        '此选项不会替原 SCF 开启 SOC，也不能把标量模型变成 spinor 模型。',
        'yes / no（在菜单中选择是或否）', _RESTORE + '关闭时保留轨道项，不请求额外自旋项。'),
}
