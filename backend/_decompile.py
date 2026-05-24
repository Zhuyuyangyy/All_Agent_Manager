import dis, marshal, types

with open(r"D:\ZYY Project\All_Agent_Manager\backend\__pycache__\app.cpython-312.pyc", "rb") as f:
    f.read(16)  # skip header
    code = marshal.load(f)

# Print all top-level names and string constants
print("=== CONSTANTS ===")
for c in code.co_consts:
    if isinstance(c, str) and len(c) > 10:
        print(repr(c[:200]))
    elif isinstance(c, types.CodeType):
        print(f"CODE: {c.co_name} (line {c.co_firstlineno})")
        for cc in c.co_consts:
            if isinstance(cc, str) and len(cc) > 10:
                print(f"  {repr(cc[:200])}")
            elif isinstance(cc, types.CodeType):
                print(f"  CODE: {cc.co_name} (line {cc.co_firstlineno})")

print("\n=== NAMES ===")
print(code.co_names)
