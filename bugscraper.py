from argparse import ArgumentParser # for CL args
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir
import re # regex
from sys import exit # "quit" in interactive mode
from time import sleep # to enforce crawl-delay
from urllib.request import urlopen # grabs a page's HTML
from copy import copy

from bs4 import BeautifulSoup # creates a navigable parse tree from the HTML
from bs4 import Tag
import jinja2 as jin
from rich import print # for CL pretty
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text


def make_soup(url: str) -> BeautifulSoup:
    """
    Validates the URL and returns the corresponding soup. Things that aren't URLs for BugGuide,
    or that appear to be but for the wrong sections of BugGuide, will raise a RuntimeError
    """
    # Is this obviously not a BugGuide URL?
    try:
        url.index("bugguide.net")
    except ValueError:
        raise RuntimeError("Hey, this isn't BugGuide!")

    # Is this a URL for one of the other Guide tabs? (excluding "Info," which has no suffix and so can't be distinguished without visiting)
    wrong_tab = re.search('bugguide\.net/node/view/\d+/(tree|bgpage|bglink|bgref|data)', url)
    if wrong_tab:
        # If so, it can be corrected without fetching the wrong page first
        url = url[:wrong_tab.start(1)] + "bgimage"
        print(f"Not an images page, converting to {url}...")

    # Fetch the page
    html = urlopen(url).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    # The "Taxonomy-Browse-Info-Images-Links-Books-Data" tabs are only present when in the Guide
    menubar = soup.find(class_="guide-menubar")
    # Menubar element is present on non-guide pages but empty
    if not menubar or not menubar.get_text():
        raise RuntimeError("Oops, this isn't a guide page!")
    # If "Images" tab is selected, great, we're all set
    img_tab = menubar.find(string="Images").parent
    if img_tab.name != 'a' and img_tab['class'].count("guide-menubar-selected"):
        return soup
    
    # Unexpected URLs that made it this far are part of the guide for a specific taxon, just the wrong part; find the associated correct URL and use that
    correct_url = img_tab['href']
    # Pull the taxon name from the page breadcrumbs for better error messaging, since we're already here
    taxon = taxon_from_breadcrumbs(soup, use_rank=True, itals=True)
    # If no tab is currently selected, this is an individual record page
    if not menubar.find(class_="guide-menubar-selected"):
        print(f"URL is for record in [b]{taxon}[/b]")
    # Otherwise some other tab (i.e. "Info") is selected
    else:
        print(f"URL is for guide page in [b]{taxon}[/b]")
    print(f"Fetching all images for [b]{taxon}[/b] from {correct_url}")
    
    sleep(9)
    html = urlopen(correct_url).read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")


def taxon_from_breadcrumbs(soup, *, use_rank=False, itals=False) -> str:
    """Extracts the taxon name (and potentially rank) from the end of the first set of breadcrumbs found"""

    taxon_tag = soup.find(class_="bgpage-roots").find_all("a")[-1]
    taxon_rank = taxon_tag['title'].lower() if taxon_tag['title'] != 'No Taxon' else ''
    if itals and re.search('genus|species', taxon_rank, flags=re.I):
        taxon = '[i]'+taxon_tag.get_text()+'[/i]'
    else:
        taxon = taxon_tag.get_text()
    return taxon_rank + ' ' + taxon if use_rank else taxon


def print_comments(comments: list, muted=False) -> None:
    """Prints boxes with the comments' subject, body, and byline text to the terminal. If "muted", comments will print in italicized gray text"""

    border = "cyan on black" if not muted else "bright_black i on black"
    style = "on black" if not muted else "bright_black i on black"
    for c in comments:
        title = Text(c.find(class_="comment-subject").get_text().strip())
        body = Text(c.find(class_="comment-body").get_text().strip())
        subtitle = Text(c.find(class_="comment-byline").get_text().strip())

        print(Padding(Panel(body, 
                            title=title, title_align="left", 
                            subtitle=subtitle, subtitle_align="left", 
                            style=style, border_style=border), (1,4,0,4)))
    print(" ")


def approve_comments(comments: list) -> bool:
    """Prints a given list of comments to the terminal, prompts user whether to save them, and returns True or False accordingly. Raises SystemExit if user opts to quit instead"""

    # Print comments to terminal for manual review
    s = 's' if len(comments) != 1 else ''
    print(f"> Found {len(comments)} comment{s}:")
    print_comments(comments)
    
    # Prompt user
    print("\n[bold]Make record? (y/n/q) >>> ", end="")
    cmd = input().strip().lower()
    while cmd not in ['y', 'n', 'q']:
        print("Unrecognized command. Please enter 'y' to save to file, 'n' to discard and continue, or 'q' to quit", "[bold]>>> ", sep="\n", end="")
        cmd = input().strip().lower()
    if cmd == 'q':
        exit()
    return cmd == 'y'

# REFACTORED
def comment_html(raw_comment: Tag, soup: BeautifulSoup) -> Tag:
    """Returns a cleaned-up Tag object constructed from the given raw Tag object"""
    new_comment = soup.new_tag("div", attrs={"class": "comment"})
    # Get the components of interest
    subj, body, byline = raw_comment.select(".comment-subject, .comment-body, .comment-byline")
    # Check if there's actual user commentary in this comment besides "Moved from ___"
    if not re.match('Moved from .+\.\s*$', body.get_text(), flags=re.I):
        new_comment["class"].append("mark")
    # If the user didn't give the comment a subject line, BG just replicates the start of the body text for it
    if body.get_text()[:len(subj.get_text())] == subj.get_text():
        subj['style'] = "display: none"
    # .comment-byline is a td, reformat it
    byline.name = "div"
    del byline['width']
    # Carry over reply indent (replies are wrapped in the second td of a table, and use the first td's width as the indent)
    if raw_comment.parent.name == 'td':
        indent = int(raw_comment.parent.previous_sibling["width"])
        new_comment['style'] = f'margin-left: {indent//25*2}rem'
    
    new_comment.extend([subj, body, byline])
    return new_comment


def record_html(soup: BeautifulSoup, url, comments: list) -> Tag:
    """Makes it all pretty in HTML."""
    # desc_box has two cols, for a thumbnail image & the user-provided metadata/details
    desc_box = soup.new_tag("div", attrs={"class": "desc-container"})
    # Col 1: image
    img = soup.find(class_="bgimage-image")
    # Col 2: record info
    desc = soup.new_tag("div", attrs={"class": "desc"})
    header = soup.find(class_="node-title")
    header.name = 'h3'
    header.attrs = {}
    # If one or both M/F symbols are present, convert to text
    symbols = header.find_all("img")
    if symbols:
        header.append(symbols[0]['alt'].lower())
        header.img.decompose()
        if len(symbols) == 2:
            header.append(' & ' + symbols[1]['alt'].lower())
            header.img.decompose()
    desc.append(header)
    # Location, date, and/or size
    metadata = soup.find(class_="bgimage-where-when")
    desc.append(metadata)
    # User-provided description
    remarks = soup.find(class_="node-body")
    if remarks:
        desc.append(remarks)
    # Add the two columns
    desc_box.append(img.wrap(soup.new_tag("a", href=url)))
    desc_box.append(desc)

    ref = soup.new_tag('a', href=url)
    ref.string = url

    obs = soup.new_tag("article")
    obs.extend([desc_box, ref, *comments])
    return obs


def process_record(url: str) -> Tag | None:
    """Builds and returns record summary as Tag object, if comments are found and one of the following conditions is met:
    (1) --ignore-moves is not set, or:
    (2) --ignore-moves is set and there are non-move comments 
        (ignore='nochat' records all comments, ignore='always' records only the non-move comments)
    Otherwise, returns None"""

    html = urlopen(url).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")

    raw_comments = soup.find_all(class_="comment")
    # If no comments found at all, exits here
    if not raw_comments:
        print("> No comments found")
        return
    # Extract comment info and reformat for HTML output
    processed = [comment_html(c, soup) for c in raw_comments]
    s = 's' if len(processed) != 1 else ''
    punct = ':' if args.verbose else ''
    if args.ignore_moves:
        marked, unmarked = [], []
        for c in processed: 
            if 'mark' in c['class']: marked.append(c)
            else: unmarked.append(c)
        if unmarked:
            # 'nochat' skips move comments if they aren't potentially part of a conversation (i.e. there's no comments besides the move comments)
            if (args.ignore_moves == 'nochat' and not marked) or args.ignore_moves == 'always':
                s2 = 's' if len(unmarked) != 1 else ''
                print(f"> Skipped {len(unmarked)} move comment{s2}{punct}")
                # Print what's being skipped in verbose mode
                if args.verbose: 
                    print_comments(unmarked, muted=True)
                if not marked:
                    # Skipping everything, so exit here
                    return
                # 'always' = Write only the marked comments to file
                processed = marked

    # Interactive mode checks in with the user before writing
    if args.screen and not approve_comments(processed):
        # If user isn't interested in saving this set of comments, exits here
        print(f"> Skipped {len(processed)} move comment{s}")
        return

    print(f"> Importing {len(processed)} comment{s}{punct}")
    # (screen_before_write() prints, so avoid printing again here in interactive mode)
    if args.verbose and not args.screen: 
        print_comments(processed)
    
    return record_html(soup, url, processed)


def traverse_guide(start_url, f, soup) -> None:
    """Handles iterating over multiple pages"""

    # Overall header for the output
    f.write(str(soup.find(class_="node-title").h1)+"\n")
    # Construct subheading Tag for later
    subheading = soup.new_tag("div", attrs={"class": "taxon"})

    start_section = soup.select_one(".node-main-alt, .node-main")
    roots = start_section.find(class_="bgpage-roots")
    h2 = soup.new_tag("h2")
    h2.string = roots.get_text()

    guide_self = soup.new_tag("a", href=roots.find_all("a")[-1]['href'])
    guide_self.string = "images for this taxon"
    guide_parent_pos = soup.new_tag("a", href=start_url)
    guide_parent_pos.string = "position in parent taxon's images"
    subhead_links = soup.new_tag("p")
    subhead_links.extend(['|', guide_self, '|', guide_parent_pos, '|' ])

    subheading.extend([h2, subhead_links])

    # While there's a page of thumbnails to process:
    url = start_url
    while url:
        sleep(9) # Crawl-delay from BG's robots.txt

        # Fetch page's HTML and make soup, if you haven't already
        if url != start_url:
            html = urlopen(url).read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")

        # Check the pager for current page number
        try:
            page = soup.find(class_="pager").find("b").get_text()
        except AttributeError: 
            # Single-page results don't have a pager
            page = "1"

        # Pull the page sections that have image links in them
        taxon_sections = soup.select(".node-main, .node-main-alt")
        try:
            for sec in taxon_sections:
                # Update CL with current page number + taxon
                taxon = taxon_from_breadcrumbs(sec)
                print(f"Scanning page {page} submissions for '{taxon}'...")

                # If section name is new, update subheading text and write to HTML
                breadcrumbs = sec.find(class_="bgpage-roots").get_text()
                if breadcrumbs != h2.get_text():
                    h2.string = breadcrumbs
                    guide_self['href'] = roots.find_all("a")[-1]['href']
                    guide_parent_pos['href'] = url
                    f.write(str(subheading))

                # For each record in this section:
                for img in sec.find_all("a", recursive=False):
                    img_url = img.get('href')
                    print(f"Checking [i cyan]{img_url}")
                    sleep(9) # Crawl-delay from BG's robots.txt
                    # Format text for HTML output
                    block = process_record(img_url)
                    # Write to file
                    if block: f.write(str(block))

        except (SystemExit, KeyboardInterrupt):
            print("\nExiting scan...")
            return
        
        # Check if there's another page to do
        next_arrow = soup.find(alt="next page")
        url = next_arrow and next_arrow.parent.get('href')


def validate_file_name(taxon_title) -> str:
    if not args.fname:
        name = taxon_title
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


def guidechat_to_html(url=None) -> None:
    """Main bot loop, does all the things from here. If not directly passed a URL as an arg, or if the URL
    is bad and it needs another one, will prompt for one at the command line"""
    if not url:
        print("[bold]Start checking image comments on: ", end="")
        url = input()
    soup = None
    while not soup:
        # TODO: Add "help" and "quit" support
        try:
            soup = make_soup(url)
        except Exception as err:
            print("[dark_orange]" + str(err))
            print("[bold]Start checking image comments on: ", end="")
            url = input()

    if not exists('comments'):
        mkdir('comments')

    taxon = taxon_from_breadcrumbs(soup)
    file_name = validate_file_name(taxon)

    # TODO: error handling for write permissions failure
    with open(file_name, "w", encoding="utf-8") as f:
        print(f"\nWriting results to '{file_name}'")
        # Start off the file with some style instructions
        with open("comments.css", "r") as css:
            f.write("<style>\n")
            for line in css:
                f.write("\t"+line)
            f.write("\n</style>\n")

        traverse_guide(url, f, soup)
    # File closed, reprint file name for ease of reference
    print(f"Results saved to '{file_name}'")


if __name__ == '__main__':
    global args
    desc = "Scans BugGuide's user submissions under a particular species or other taxon, and collects submission comments that might have interesting discussions or identification tips. Default output format is an .html file with some bare-bones styling for readability."
    parser = ArgumentParser(description=desc)
    # --screen
    parser.add_argument('--screen', action="store_true",
                        help='interactive mode: print each set of comments found and ask for user approval before saving them')
    # -i, --ignore-moves ['always' or 'nochat']
    parser.add_argument('--ignore-moves', choices=['always', 'nochat'],
                        help='skip auto-generated move comments from editors ("Moved from Potter and Mason Wasps.") unless the editor added additional commentary to the body text; "nochat" only skips if *all* of the comments are move comments, to preserve conversational context about misclassifications')
    # -v, --verbose
    parser.add_argument('-v', '--verbose', action="store_true",
                        help='print every comment found, even if not saving them')
    # --fname [filename]
    parser.add_argument('--fname',
                        help='name for .html output file; otherwises uses taxon name')
    # -r, --replace
    parser.add_argument('-r', '--replace', action="store_true",
                        help='if a file with this name already exists, overwrite it')
    # --url [url]
    parser.add_argument('--url',
                        help='starting URL; must be associated with the guide for a specific taxon; if this doesn\'t link directly into the guide\'s image list, it will find the associated image list and start on page 1')

    args = parser.parse_args()

    guidechat_to_html(args.url)