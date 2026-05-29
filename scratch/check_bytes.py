with open("mk.xml", "rb") as f:
    content = f.read()

# Let's find the bytes of the channel title
start_idx = content.find(b"<title><![CDATA[")
if start_idx != -1:
    end_idx = content.find(b"]]></title>", start_idx)
    raw_title_bytes = content[start_idx:end_idx+11]
    print(f"Raw title bytes: {raw_title_bytes}")
    
    # Try decoding just the CDATA content
    cdata_bytes = content[start_idx+16:end_idx]
    print(f"CDATA bytes: {cdata_bytes}")
    
    try:
        decoded = cdata_bytes.decode('utf-8')
        print(f"Decoded UTF-8 successfully. Chars: {[ord(c) for c in decoded]}")
        print(f"Decoded string representation: {repr(decoded)}")
    except Exception as e:
        print(f"Decoded UTF-8 failed: {e}")
        
    try:
        decoded_euc = cdata_bytes.decode('euc-kr')
        print(f"Decoded EUC-KR successfully. Chars: {[ord(c) for c in decoded_euc]}")
        print(f"Decoded EUC-KR string representation: {repr(decoded_euc)}")
    except Exception as e:
        print(f"Decoded EUC-KR failed: {e}")
else:
    print("Not found channel title")
