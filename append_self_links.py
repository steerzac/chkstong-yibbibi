import os

do_not_append_files = ["P3Codes.zip",
                        "README.md",
                        "Google_Trends.html",
                        "append_self_links.py",
                        "a_helper_scripts.py"]

for file in os.listdir("."):
    if os.path.isfile(file) and file not in do_not_append_files:
        with open(file, "a") as f:
            print(file)
            f.write("https://github.com/steerzac/chkstong-yibbibi")
