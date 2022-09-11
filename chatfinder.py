from argparse import ArgumentParser # for CL args
from copy import copy
from html import unescape # for later(?)
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir
import re # regex
from sys import exit # "quit" in interactive mode
from time import sleep # to enforce crawl-delay
from urllib.request import urlopen # grabs a page's HTML

from bs4 import BeautifulSoup # creates a navigable parse tree from the HTML
from bs4 import Tag
import jinja2 as jin # templating engine
from rich import print # for CL pretty
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text
import rich.repr


class Comment:
    """Contains extracted HTML text and some simple style markers from a single comment on a record page
    
    Instance attributes
    -------------------
    html : dict
        Unicode string of the contents of div.comment-subject, div.comment-body, and div.comment-byline
        subj : str
        body : str
        byline : str
    style : dict
        Metadata for conditional styling with the templating engine
        highlight : bool
            True if the body contains text besides "Moved from ___"
        subj_repeats : bool
            True if the subject line just repeats the first >=30(?) characters of the body text
        indent : int
            How much to indent a nested reply comment (converts BugGuide's 25px indent increments to multiples of 2rem)
    """

    def __init__(self, tag: Tag):
        self.html = {}
        self.style = {}

        # Pull text sections
        self.html['subj'] = tag.find(class_="comment-subject").decode_contents().strip()
        self.html['body'] = tag.find(class_="comment-body").decode_contents().strip()
        self.html['byline'] = tag.find(class_="comment-byline").decode_contents().strip()

        # If the user omitted a subject line, BG just fills it with body text
        self.style['subj_repeats'] = self.html['body'][:len(self.html['subj'])] == self.html['subj']
        # Highlight things other than (or in addition to) "Moved from ___"
        self.style['highlight'] = not re.match('Moved from .+\.\s*$', self.html['body'], flags=re.I)
        # Replies are wrapped in the second td of a table, and use the first td's width as the indent
        if tag.parent.name == 'td':
            indent = int(tag.parent.previous_sibling['width'])
            self.style['indent'] = indent // 25 * 2
        else: 
            self.style['indent'] = 0

    def __rich_repr__(self):
        yield "style", self.style
        yield "subj", self.html['subj']
        yield "body", self.html['body']
        yield "byline", self.html['byline']

class Record:
    """Contains all data of interest from the page for a BugGuide image submission
    
    Instance attributes
    -------------------
    url : str
        URL for the page this data corresponds to
    img : str
        URL for the image
    title : str
        User-provided image title, taxon name, and/or creature sex(es); taxon name is always present, the other two are optional
    metadata : str
        Location, date, and/or size; all fields are optional, and if all are absent this attribute's value will be an empty string
    remarks : str
        User-provided general description; often absent
    byline : str
        Username, upload date, and last edited date; first two parts are always present
    comments : list : Comment
        All comments that appear on this page, in display order (i.e. reverse chrono)
    """

    def __init__(self, soup: BeautifulSoup):
        # .bgimage-id contains the text "Photo#[number]", which is the same ID number used by the record's URL
        url_node = int(soup.find(class_="bgimage-id").get_text()[6:])
        self.url = f"https://bugguide.net/node/view/{url_node}"
        self.img = soup.find(class_="bgimage-image")["src"]
        # If one or both M/F symbols are present in title, replace symbol gif with text before decoding the Tag object
        title_tag = copy(soup.find(class_="node-title"))
        symbols = title_tag.find_all("img")
        if symbols:
            # Alt text is either "Male" or "Female"
            title_tag.append(symbols[0]['alt'].lower())
            title_tag.img.decompose()
            if len(symbols) == 2:
                title_tag.append(' & ' + symbols[1]['alt'].lower())
                title_tag.img.decompose()
        self.title = title_tag.decode_contents().strip()
        # div.bgimage-where-when is reliably present but may be empty
        self.metadata = soup.find(class_="bgimage-where-when").decode_contents().strip()
        # div.node-body is absent if the user provided no description
        node_body = soup.find(class_="node-body")
        self.remarks = node_body and node_body.decode_contents().strip() or ''
        self.byline = soup.find(class_="node-byline").decode_contents().strip()

        # List of comments as Comment objects
        self.comments = [Comment(c) for c in soup.find_all(class_="comment")]

    def __rich_repr__(self):
            yield "page_src", self.url
            yield "image_src", self.img
            yield "title", self.title
            yield "metadata", self.metadata
            yield "remarks", self.remarks
            yield "byline", self.byline
            yield self.comments

class Section:
    """Contains metadata and records pulled from a section within a specific taxon

    The guide images for taxa above species/subspecies level include the images of all descendant taxa, grouped into sections (which are displayed in sorted order corresponding to a depth-first search of the taxonomical hierarchy). A Section object may span one or more pages of results. If there are no descendant taxa, the search will result in just one Section object

    Instance attributes
    -------------------
    title : str
        The "»"-separated list of taxa in between this taxon and the parent taxon that appears at the top of its section. When created from process_list_page(), 
    rank : str
        Level in the taxonomic hierarchy, e.g. "species" or "subtribe". When created from process_list_page(), the rank will be in lowercase
    taxon : str
        Taxon name used by BugGuide, which may include both a scientific name and a common name, and occasionally other signifiers such as Hodges number
    own_page : str
        Page 1 of the Images tab for this taxon by itself
    parent_page : str
        The first page that this taxon was originally encountered on within the Images tab of its parent (position may have changed since the scan was done)
    records : list[Record]
    """
    def __init__(self, title, rank, taxon, *, own_page, parent_page):
        # Taxon data
        self.title = title
        self.rank = rank
        self.taxon = taxon
        # Links
        self.own_page = own_page
        self.parent_page = parent_page
        # Record objects
        self.records = []

    def __rich_repr__(self):
        yield "title", self.rirlw
        yield "rank", self.rank
        yield "taxon", self.taxon
        yield "self link", self.own_page
        yield "parent link", self.parent_page
        yield self.records


# Get taxon rank and name text from breadcrumbs
def taxon_from_breadcrumbs(tag, text_format=None) -> tuple:
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


# Process sections within a single page
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
        print(f"--------\nScanning page {page} submissions for '{taxon_tup[1]}'...\n--------")

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
            sleep(9)

            html = urlopen(record_url).read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            record = process_record(soup)
            if record:
                all_sections[-1].records.append(record)


# Return a probably-okay URL or die trying
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


# Return some okay soup or die trying
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
    

# Generate an output file name in accordance with args
def name_file(taxon: str) -> str:
    if not args.fname:
        name = taxon
    else:
        # TODO: validate filename?
        # should at minimum strip any provided extension, I think
        name = args.fname

    # Avoid overwriting files unless given permission
    if not args.replace:
        ver = 1
        vername = name
        while exists("comments/"+vername+".html"):
            vername = f"{name} ({ver})"
            ver += 1
        name = vername
    return "comments/"+name+".html"


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


if __name__ == '__main__':
    global args
    args = parser().parse_args()

    # TODO: More informative prompt text
    if not args.url:
        print("[bold]Start checking image comments on: ", end="")
        url = input()
    url = check_url(url)

    html = urlopen(url).read().decode("utf-8")
    soup = check_soup(BeautifulSoup(html, "html.parser"))

    if not exists('comments'):
        mkdir('comments')

    taxon = taxon_from_breadcrumbs(soup)
    file_name = name_file(taxon[1])

    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")
    context = {"url": url, "parent_rank": taxon[0], "sections": []}

    # TODO: error handling for write permissions failure
    # TODO: more graceful handling of KeyboardInterrupt
    with open(file_name, "w", encoding="utf-8") as f:
        try:
            # While there's still pages of results to fetch:
            while url:    
                if not context["sections"]:
                    # Start of loop, so add the page header to context
                    title_tag = soup.find(class_="node-title")
                    # First element of tuple has italics, second is plaintext version
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
    
