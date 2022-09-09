from itertools import product
from traceback import print_exception
from chatfinder import *

def taxon_from_breadcrumbs(soup, text_format=None, use_rank=False) -> str:
    """Extracts the taxon name (and potentially rank) from the end of the first set of breadcrumbs found
    
    text_format, if present, should be one of ("console", "html") and determines if/how species and genus names are italicized """

    taxon_tag = soup.find(class_="bgpage-roots").find_all("a")[-1]
    taxon_rank = taxon_tag['title'].lower() if taxon_tag['title'] != 'No Taxon' else ''

    taxon = taxon_tag.get_text()
    if re.search('genus|species', taxon_rank, flags=re.I):
        if text_format == "console":
            taxon = '[i]' + taxon + '[/i]'
        elif text_format == "html":
            taxon = '<i>' + taxon + '</i>'
    return taxon_rank + ' ' + taxon if use_rank else taxon

# Log one processed record to the terminal
def log_comments(comms, type="import") -> None:
    """Print an update to the terminal for this set of comments"""

    if comms == None:
        return

    # Log action being taken
    s = 's' if len(comms) != 1 else ''
    if type == "import":
        print(f"> Importing {len(comms)} comment{s}{':' if args.verbose else ''}")
    elif type == "skip":
        print(f"> Skipped {len(comms)} comment{s}{':' if args.verbose else ''}")
    elif type == "screen":
        print(f"> Found {len(comms)} comment{s}:")
    else:
        raise ValueError("Log type must be in ['import', 'skip', 'screen']")

    # In verbose mode, also log the comment text
    if args.verbose or type == "screen":
        # Black background is for color contrast purposes, to keep light gray text readable on an arbitrary terminal background color
        if type == "skip":
            border = style = "bright_black i on black"
        else:
            border = "cyan on black"
            style = "on black"
        
        for c in comms:
            body = re.sub("<[^<]+?>", "", c.html['body'])
            subject = re.sub("<[^<]+?>", "", c.html['subj'])
            byline = re.sub("<[^<]+?>", "", c.html['byline'])
            print(Padding(Panel(body, 
                                title=subject, title_align="left", 
                                subtitle=byline, subtitle_align="left", 
                                style=style, border_style=border), (1,4,0,4)))
        print(" ")


# Extract data from one record page
def process_record(soup) -> Record | None:
    """Build a Record object based on the soup and print some info about it according to user prefs"""

    rec = Record(soup)

    if not rec.comments:
        print("> No comments found")
        return None

    # Filter record and/or specific comments based on comment content and user args
    if args.ignore_moves:
        marked, unmarked = [], []
        for c in rec.comments:
            if c.style['highlight']: marked.append(c)
            else: unmarked.append(c)
        # If none are highlighted, discard the record
        if not marked:
            log_comments(rec.comments, "skip")
            return None
        if args.ignore_moves == "always":
            # Discard all non-highlighted comments
            if unmarked:
                log_comments(unmarked, "skip")
            rec.comments = marked
    
    # Manual screening for remainder of comments
    if args.screen:
        log_comments(rec.comments, "screen")
        # Prompt user
        print("\n[bold]Save record? (y/n/q) >>> ", end="")
        cmd = input().strip().lower()
        while cmd not in ['y', 'n', 'q']:
            print("Unrecognized command. Please enter 'y' to save to file, 'n' to discard and continue, or 'q' to quit", "[bold]>>> ", sep="\n", end="")
            cmd = input().strip().lower()
        if cmd == 'y':
            print(f"> Importing {len(rec.comments)} comment{'s' if len(rec.comments) != 1 else ''}")
            return rec
        elif cmd == 'n':
            print("> Record skipped")
            return None
        else:
            exit()

    log_comments(rec.comments, "import")
    return rec


# [testing] Just makes soup
def make_test_soup(url) -> BeautifulSoup:
    # Shorter sleep time for dev purposes since only requesting a handful of pages at a time
    sleep(2)
    html = urlopen(url).read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")

# [testing] Separating out the parser definition for code block collapse purposes
def parser() -> ArgumentParser:
    desc = "Scans BugGuide's user submissions under a particular species or other taxon, and collects submission comments that might have interesting discussions or identification tips. Default output format is an .html file with some bare-bones styling for readability."
    p = ArgumentParser(description=desc)
    # --screen
    p.add_argument('--screen', action="store_true",
                        help='interactive mode: print each set of comments found and ask for user approval before saving them')
    # -i, --ignore-moves ['always' or 'nochat']
    p.add_argument('--ignore-moves', choices=['always', 'nochat'],
                        help='skip auto-generated move comments from editors ("Moved from Potter and Mason Wasps.") unless the editor added additional commentary to the body text; "nochat" only skips if *all* of the comments are move comments, to preserve conversational context about misclassifications')
    # -v, --verbose
    p.add_argument('-v', '--verbose', action="store_true",
                        help='print every comment found, even if not saving them')
    # --fname [filename]
    p.add_argument('--fname',
                        help='name for .html output file; otherwises uses taxon name')
    # -r, --replace
    p.add_argument('-r', '--replace', action="store_true",
                        help='if a file with this name already exists, overwrite it')
    # --url [url]
    p.add_argument('--url',
                        help='starting URL; must be associated with the guide for a specific taxon; if this doesn\'t link directly into the guide\'s image list, it will find the associated image list and start on page 1')
    return p


def main(url):
    global args
    args = parser().parse_args()
    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")

    print("Checking [i cyan]" + url)
    # sleep(9)
    # Fetch and parse the page contents
    html = urlopen(url).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    print(process_record(soup))

    with open(f"tests/test.html", "w", encoding="utf-8") as f:
        
        section_records = []
        try:
            rec = process_record(soup)
            if rec: section_records.append(rec)
        except Exception as e:
            print(f"[dark_orange]Error: {e}[/dark_orange]\n  (verbose, screen, ignore_moves) = {cfg}\n  '{url}'")
            print_exception(e)
        
        f.write(template.render({"records": section_records}))



def test_comment_processing():
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
    # Generate all combinations of options using cartesian product
    options = {
        "verbose": (True, False),
        "screen": (False, True),
        "ignore_moves": (None, "always", "nochat"),
    }
    configs = list(product(*options.values()))

    # Simple data structure to emulate ArgumentParser's Namespace class, in place of real CL args
    class Config:
        # Note: args must be in the same order as in the options dict
        def __init__(self, verbose=False, screen=False, ignore_moves=None):
            self.verbose = verbose
            self.screen = screen
            self.ignore_moves = ignore_moves

    global args
    # Set up template engine
    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")

    # Load all the soups from cases once, then use with each config
    print("(Making soup...)")
    soups = [(url, make_test_soup(url)) for url in cases.values()]

    for url, soup in soups:
        # Process the record with each config
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


if __name__ == '__main__':
    test_comment_processing()
    





# --------------------------------------------------------------
# Old test functions
misc_cases = {
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

def test_imagelist(which):
    cases = {
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
        # Pyrausta, page 9 - 3 sections
        "py": "https://bugguide.net/node/view/9722/bgimage?from=192",
    }
    soup = make_test_soup(cases[which])
    container = soup.find(class_='node-main-alt')
    test = container.contents[0]
    print(test.contents[-1].get_text())
