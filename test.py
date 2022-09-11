from itertools import product
from traceback import print_exception
from chatfinder import *

def make_test_soup(url):
    html = urlopen(url).read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")



# Semi-automated record test cases
def test_comment_processing():
    """Semi-automated test series to validate console and HTML output with different config options and record states"""
    cases = {
        # no comments (C emarginata)
        # "nocom": "https://bugguide.net/node/view/2158558",

        # only move comments (just 1 here) (Disonycha)
        "move": "https://bugguide.net/node/view/1548798/bgimage",

        # interleaved move & chat comments (Parazumia)
        "inter": "https://bugguide.net/node/view/1425862/bgimage",

        # chat comment that replies to move comment (Parazumia)
        "paraz": "https://bugguide.net/node/view/1550456/bgimage",
    }
    # Generate all combinations of options using Cartesian product
    options = {
        "verbose": (True, False),
        "screen": (False, True),
        "ignore_moves": (None, "always", "nochat"),
    }
    configs = list(product(*options.values()))

    # Simple data structure to emulate ArgumentParser's Namespace class, in place of real CL args
    class Config:
        # (Note: args must be in the same order as in the options dict)
        def __init__(self, verbose=False, screen=False, ignore_moves=None):
            self.verbose = verbose
            self.screen = screen
            self.ignore_moves = ignore_moves

    global args
    # Set up template engine
    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")

    # Load all the soups once, then reuse the parse tree with each config
    print("(Making soup...)")
    soups = [(url, make_test_soup(url)) for url in cases.values()]

    for url, soup in soups:
        # Process the record using each config
        for cfg in configs:
            with open(f"tests/test.html", "w", encoding="utf-8") as f:
                args = Config(*cfg)
                records = []
                print(f"\n[cyan]With...[/cyan]\n  (verbose, screen, ignore_moves) = {cfg}\n  '{url}'\n")
                try:
                    rec = process_record(soup)
                    if rec: records.append(rec)
                except Exception as e:
                    print(f"[dark_orange]Error: {e}[/dark_orange]\n  (verbose, screen, ignore_moves) = {cfg}\n  '{url}'")
                    print_exception(e)
                
                f.write(template.render({"records": records}))

            print("\n[cyan]Continue testing? y/n [cyan]>>> ", end="")
            cmd = input().strip().lower()
            while cmd not in ['y', 'n']:
                print("Unrecognized command", "[bold]>>> ", sep="\n", end="")
                cmd = input().strip().lower()
            if cmd == 'n':
                exit(0)

# ----------------------------------------------------------
url_check_cases = [
    # not a URL
    "heywaitaminute", 
    # not a URL but mildly sneaky about it
    "hello i am definitely bugguide.net",
    # not BugGuide
    "https://www.example.com/",
    # yes BugGuide but the beta
    "https://beta.bugguide.net/node/75511/bgimage?from=36",
    # yes BugGuide but not the guide
    "https://bugguide.net/help",
    # yes BugGuide guide but wrong tab
    "https://bugguide.net/node/view/75511/data",
    # yes BugGuide guide but wrong tab and this time it's the Info tab
    "https://bugguide.net/node/view/75511",
    # yes BugGuide guide but it's an individual record
    "https://bugguide.net/node/view/1842547",
]

misc_record_cases = {
    # 2x two-level nested comments, comments with repetitive subject lines (C purpurata)
    # "pur": "https://bugguide.net/node/view/1655314/bgimage",

    # four-level nested comment (C emarginata)
    # "emarg": "https://bugguide.net/node/view/200792/bgimage",

    # Individual photo for a species (C. emarginata)
    "sp-rec": "https://bugguide.net/node/view/1421086/bgimage",

    # not a BugGuide URL
    # "err": "https://www.example.com/",

    # male & female (Zethus spinipes)
    # "mf": "https://bugguide.net/node/view/2141976",

    # taxon above genus (Cassidini)
    # "cassid": "https://bugguide.net/node/view/2136800/bgimage",

    # Data tab for a higher 'no-name' taxon
    "cucuji": "https://bugguide.net/node/view/1117170/data",

    # Info tab for Class Insecta
    "insecta": "https://bugguide.net/node/view/52",
}

misc_section_cases = {
    # Pyrausta, page 9 - 3 sections
    "py": "https://bugguide.net/node/view/9722/bgimage?from=192",
    # Charidotella emarginata — 1 page (13 links), almost all comments are "Moved from"
    "emarg": "https://bugguide.net/node/view/202390/bgimage",
    # Charidotella purpurata - 2 pages, decent number of short discussions
    "pur": "https://bugguide.net/node/view/75511/bgimage",
    "pur-p2": "https://bugguide.net/node/view/75511/bgimage?from=24",
    # Jonthonota nigripes - 2 pages
    "jon": "https://bugguide.net/node/view/13536/bgimage",
    # Falsomordellistena pubescens - 5 pages
    "falso": "https://bugguide.net/node/view/172080/bgimage",
    # Mordellochroa scapularis - 3 pages
    "chroa": "https://bugguide.net/node/view/126557/bgimage",
}

cases = {
    # Charidotella emarginata — 1 page (13 links), almost all comments are "Moved from"
    "emarg": "https://bugguide.net/node/view/202390/bgimage",
    # Scymnus - final page (24 links); one non-taxonomic group + 4 spp, only the second of which has a common name
    "scym": "https://bugguide.net/node/view/51632/bgimage?from=547",
    # Charidotella purpurata - 2 pages, decent number of short discussions
    "pur": "https://bugguide.net/node/view/75511/bgimage",
    "pur-p2": "https://bugguide.net/node/view/75511/bgimage?from=24",
    # Jonthonota nigripes - 2 pages
    "jon": "https://bugguide.net/node/view/13536/bgimage",
    # Falsomordellistena pubescens - 5 pages
    "falso": "https://bugguide.net/node/view/172080/bgimage",
    # Mordellochroa scapularis - 3 pages
    "chroa": "https://bugguide.net/node/view/126557/bgimage",
    # Pyrausta, page 8 - 3 sections
    "py": "https://bugguide.net/node/view/9722/bgimage?from=178",
}
