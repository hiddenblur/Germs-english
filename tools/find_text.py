"""List real-looking strings (null-terminated, SJIS + ASCII, containing kana).

Usage: python tools/find_text.py <file> [min_kana]
Prints: offset, length, decoded text (ASCII control digits kept as-is).
"""
import sys


def is_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def is_kana(c):
    return 0x829F <= c <= 0x82F1 or 0x8340 <= c <= 0x8396


def scan(data, min_kana=3):
    i, n = 0, len(data)
    while i < n:
        start, kana, ok = i, 0, True
        while i < n and data[i] != 0:
            b = data[i]
            if is_lead(b) and i + 1 < n and 0x40 <= data[i + 1] <= 0xFC:
                kana += is_kana(b << 8 | data[i + 1])
                i += 2
            elif 0x20 <= b < 0x7F:
                i += 1
            else:
                ok = False
                break
        if ok and i < n and kana >= min_kana:
            yield start, data[start:i]
        i += 1


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    min_kana = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for off, raw in scan(data, min_kana):
        print(f"{off:08X} {len(raw):4d}  {raw.decode('cp932', 'replace')}")
