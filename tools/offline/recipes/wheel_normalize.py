"""Standard-library-only canonical wheel packer; execute inside pinned image."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile


def validate_record(path):
    """Require a complete SHA256 RECORD, including sizes and no extra ZIP members."""
    with zipfile.ZipFile(path) as wheel:
        members = wheel.namelist()
        records = [n for n in members if n.count('/') == 1 and n.endswith('.dist-info/RECORD')]
        if len(records) != 1 or len(set(members)) != len(members):
            raise ValueError('invalid wheel RECORD or duplicate ZIP members')
        rows = list(csv.reader(io.StringIO(wheel.read(records[0]).decode())))
        if any(len(r) != 3 for r in rows) or len({r[0] for r in rows}) != len(rows):
            raise ValueError('invalid RECORD rows')
        if {r[0] for r in rows} != {n for n in members if not n.endswith('/')}:
            raise ValueError('RECORD does not cover exact wheel members')
        for name, digest, size in rows:
            if name == records[0]:
                if digest or size:
                    raise ValueError('RECORD must not hash itself')
                continue
            data = wheel.read(name)
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            if digest != expected or size != str(len(data)):
                raise ValueError('RECORD content mismatch: ' + name)


def normalize_wheel(path, output):
    """Canonical wheel ZIP/RECORD and visible build tag; payload bytes are preserved."""
    path, output = Path(path), Path(output)
    validate_record(path)
    parts = path.name[:-4].split('-')
    filename = '-'.join([parts[0], parts[1], '1qboxcpu', *parts[-3:]]) + '.whl'
    with zipfile.ZipFile(path) as wheel:
        files = {n: wheel.read(n) for n in wheel.namelist() if not n.endswith('/')}
    record = next(n for n in files if n.count('/') == 1 and n.endswith('.dist-info/RECORD'))
    metadata = record.rsplit('/', 1)[0] + '/WHEEL'
    lines = [line for line in files[metadata].decode().splitlines() if not line.startswith('Build:')]
    files[metadata] = ('\n'.join(lines).rstrip() + '\nBuild: 1qboxcpu\n').encode()
    del files[record]
    rows = [[n, 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b'=').decode(), str(len(d))] for n,d in sorted(files.items())]
    rows.append([record,'',''])
    stream = io.StringIO(); csv.writer(stream,lineterminator='\n').writerows(rows)
    files[record] = stream.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    dest = output/filename
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as wheel:
        for member, data in sorted(files.items()):
            info=zipfile.ZipInfo(member,(2025,9,1,0,0,0))
            info.create_system=3
            info.external_attr=0o100644 << 16
            info.compress_type=zipfile.ZIP_DEFLATED
            wheel.writestr(info,data,compresslevel=9)
    validate_record(dest)
    return dest

if __name__ == '__main__':
    import sys
    for wheel in sorted(Path(sys.argv[1]).glob('*.whl')):
        print(normalize_wheel(wheel, Path(sys.argv[2])))
