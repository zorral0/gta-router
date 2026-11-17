import zipfile
import re
import sys
from xml.etree import ElementTree as ET

def col_to_idx(col):
    idx = 0
    for c in col:
        idx = idx * 26 + (ord(c) - ord('A') + 1)
    return idx - 1

def read_xlsx_sheet(path, sheet_file='xl/worksheets/sheet1.xml'):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si', ns):
                texts = si.findall('.//m:t', ns)
                shared.append(''.join(t.text or '' for t in texts))
        root = ET.fromstring(z.read(sheet_file))
        sheet_data = root.find('m:sheetData', ns)
        rows = []
        for row in sheet_data.findall('m:row', ns):
            rowdata = {}
            maxcol = 0
            for c in row.findall('m:c', ns):
                ref = c.get('r')
                colletters = re.match(r'[A-Z]+', ref).group(0)
                idx = col_to_idx(colletters)
                maxcol = max(maxcol, idx)
                t = c.get('t')
                v = c.find('m:v', ns)
                is_ = c.find('m:is', ns)
                val = None
                if is_ is not None:
                    texts = is_.findall('.//m:t', ns)
                    val = ''.join(t2.text or '' for t2 in texts)
                elif v is not None:
                    if t == 's':
                        val = shared[int(v.text)]
                    else:
                        val = v.text
                rowdata[idx] = val
            rows.append((rowdata, maxcol))
        return rows

if __name__ == '__main__':
    path = sys.argv[1]
    rows = read_xlsx_sheet(path)
    print('total rows', len(rows))
    for rowdata, maxcol in rows[:3]:
        print([rowdata.get(i) for i in range(maxcol+1)])
