def try_decode(filename):
    print(f"\n================= {filename} =================")
    with open(filename, "rb") as f:
        content = f.read()
        
    encodings = ['utf-8', 'euc-kr', 'cp949', 'utf-16']
    for enc in encodings:
        try:
            decoded = content.decode(enc)
            # Find first occurrence of '<title>'
            idx = decoded.find('<title>')
            if idx != -1:
                snippet = decoded[idx:idx+150]
                print(f"[{enc}] successfully decoded. Snippet: {repr(snippet)}")
            else:
                snippet = decoded[:150]
                print(f"[{enc}] successfully decoded (no <title>). Snippet: {repr(snippet)}")
        except Exception as e:
            print(f"[{enc}] failed: {str(e)[:100]}")

if __name__ == "__main__":
    try_decode("mk.xml")
    try_decode("hk.xml")
