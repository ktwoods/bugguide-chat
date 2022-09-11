from itertools import product
from traceback import print_exception
from chatfinder import *

def make_test_soup(url):
    html = urlopen(url).read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")


# Get taxon rank and name text from breadcrumbs
def taxon_from_breadcrumbs(tag: Tag, text_format=None) -> tuple:
    """Returns (taxon_rank : str, taxon_name : str) based on the first set of breadcrumbs found

    Taxon rank is based on the link's title attribute. Some BugGuide categories are non-taxonomic (e.g. "unidentified larvae" or "mostly pale spp") and use title="No Taxon", in which case this function returns "section" for taxon_rank
    
    text_format, if present, should be one of ("console", "html") and determines if/how species and genus names are italicized; if None or an invalid format is given, will return plaintext """

    taxon_tag = tag.find(class_="bgpage-roots").find_all("a")[-1]
    taxon_rank = taxon_tag['title'].lower() if taxon_tag['title'] != 'No Taxon' else 'section'

    taxon = taxon_tag.get_text()
    if re.search('genus|species', taxon_rank, flags=re.I):
        if text_format == "console":
            taxon = '[i]' + taxon + '[/i]'
        elif text_format == "html":
            taxon = '<i>' + taxon + '</i>'
    return taxon_rank, taxon


# Log results for one processed record to the terminal
def log_comments(comms: list, type="import") -> None:
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


# Get data from one record page
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


# Separating out the parser definition for ease of code block collapsing
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


# Processes sections within a single page
def process_list_page(soup, src: str, all_sections: list) -> None:
    # Check the pager for current page number
    try:
        page = soup.find(class_="pager").find("b").get_text()
    except AttributeError: 
        # Single-page results don't have a pager
        page = "1"
    
    # Pull the page sections that have image links in them
    page_sections = soup.select(".node-main, .node-main-alt")
    for sec in page_sections:
        # Log progress to console
        taxon_tup = taxon_from_breadcrumbs(sec, "console")
        print(f"Scanning page {page} submissions for '{taxon_tup[1]}'...\n")

        # Check if this section represents a new taxon or another chunk of the previous section
        breadcrumbs_text = sec.find(class_="bgpage-roots").get_text()
        if not all_sections or breadcrumbs_text != all_sections[-1].title:
            # Last link in section breadcrumbs = this taxon's own record list
            taxon_url = sec.find(class_="bgpage-roots").find_all("a")[-1]["href"]
            # Current url = position in parent's record list
            # Start a new section
            all_sections.append(Section(breadcrumbs_text, *taxon_tup, own_page=taxon_url, parent_page=src))
        
        for item in sec.find_all("a", recursive=False):
            record_url = item.get('href')
            print(f"Checking [i cyan]{record_url}")
            sleep(4) # Reduced crawl delay for dev purposes

            html = urlopen(record_url).read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            record = process_record(soup)
            if record:
                all_sections[-1].records.append(record)


# Returns a probably-okay URL or dies trying
def check_url(url: str) -> str:
    """
    Does some basic checks on the user-provided URL string, and asks the user for a new URL if it fails, returning whatever succeeds
    
    If a user provides a URL that is a BugGuide page and is associated with a particular taxon, but is for the wrong section of its guide, will return a corrected version of that URL
    """
    
    while True:
        try:
            # TODO: Does this look like a URL?

            # Is this from the Secret Beta Version?
            try:
                url.index("beta.bugguide.net")
            except ValueError:
                pass
            else:
                raise RuntimeError("Sorry, scanning the beta site is unsupported")

            # Is this obviously not a BugGuide URL?
            try:
                url.index("bugguide.net")
            except ValueError:
                raise RuntimeError("Hey, this isn't BugGuide!")

            # Is this a BugGuide URL but obviously not part of the guide?
            if not re.search("bugguide\.net/node/view/\d+", url):
                raise RuntimeError("Oops, this isn't a guide page!")

            # Is this a URL for one of the other Guide tabs? (excluding "Info," which has no suffix and so can't be identified by URL)
            wrong_tab = re.search("bugguide\.net/node/view/\d+/(tree|bgpage|bglink|bgref|data)", url)
            if wrong_tab:
                # If so, it can be corrected without fetching the wrong page first
                url = url[:wrong_tab.start(1)] + "bgimage"
                print(f"Not an images page, adjusting URL to {url} ...")
                sleep(3)

            return url
        
        except RuntimeError as e:
            print("[dark_orange]" + str(e))
            url = input("Please enter another URL >>> ")


# Returns an okay soup or dies trying
def check_soup(soup) -> BeautifulSoup:
    """
    Checks that this is the right kind of BugGuide page, i.e. part of the images list for a particular taxon/group, and asks the user for a new URL if not
    
    If a user provides a URL for the Info tab of a particular taxon, will navigate to the start of the images list and return the soup for that instead
    """
    while True:
        try:
            # The "Taxonomy-Browse-Info-Images-Links-Books-Data" tabs are only present when in the Guide
            menubar = soup.find(class_="guide-menubar")

            # check_url should catch the most egregious of the BugGuide-but-not-guide URLs, but as a backup check, menubar element is either absent or present but empty on non-guide pages
            if not menubar or not menubar.get_text():
                raise RuntimeError("Oops, this isn't a guide page!")
            
            # If "Images" tab is selected, great, we're all set
            img_tab = menubar.find(string="Images").parent
            if img_tab.name != 'a' and img_tab['class'].count("guide-menubar-selected"):
                return soup
            
            # Unexpected URLs that made it this far are part of the guide for a specific taxon, just the wrong part; find the associated correct URL and use that
            correct_url = img_tab["href"]

            # Pull the taxon name from the page breadcrumbs for better error messaging, since we're already here
            taxon = taxon_from_breadcrumbs(soup, "console")

            # If no tab is currently selected, this is an individual record page
            if not menubar.find(class_="guide-menubar-selected"):
                print(f"URL is for record in [b]{taxon[1]}[/b]")
            # Otherwise some other tab (i.e. "Info") is selected
            else:
                print(f"URL is for guide page in [b]{taxon[1]}[/b]")
            
            print(f"Fetching all images for [b]{taxon[1]}[/b] from {correct_url} ...")

            sleep(9)
            html = urlopen(correct_url).read().decode("utf-8")
            return BeautifulSoup(html, "html.parser")
        
        except RuntimeError as e:
            print("[dark_orange]" + str(e))
            url = check_url(input("Please enter another URL >>> "))
    


def check_filename(fname: str) -> str:
    pass


if __name__ == '__main__':
    url_check_cases = [
        # not a URL
        "hey wait a minute", 
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
    url = url_check_cases[0]

    global args
    args = parser().parse_args()

    url = check_url(url)

    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")
    context = {"url": url, "sections": []}

    file_name = "tests/test.html"
    with open(file_name, "w", encoding="utf-8") as f:
        try:
            html = urlopen(url).read().decode("utf-8")
            soup = check_soup(BeautifulSoup(html, "html.parser"))
            while url:    
                if not context["sections"]:
                    # Start of loop, so add the page header to context
                    title_tag = soup.find(class_="node-title")
                    # First element of tuple has italics, second is plaintext
                    context["header"] = (title_tag.decode_contents(), title_tag.get_text())
                else:
                    # This isn't the start of the loop, so make new soup
                    html = urlopen(url).read().decode("utf-8")
                    soup = BeautifulSoup(html, "html.parser")

                process_list_page(soup, url, context["sections"])

                # Check if there's another page to do
                next_arrow = soup.find(alt="next page")
                url = next_arrow and next_arrow.parent.get('href')
        finally:
            f.write(template.render(context))
            # Reprint file name for ease of reference
            print(f"\nResults saved to '{file_name}'")
    
    




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


# --------------------------------------------------------------
# Old testing resources
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
