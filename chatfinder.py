from argparse import ArgumentParser # for CL args
from copy import copy
from datetime import datetime as dt # for timestamping imports
from glob import glob
from html import unescape # for later(?)
import json
from math import ceil
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir
import re # regex
from sys import exit # "quit" in interactive mode
from time import sleep # enforces crawl-delay
from urllib.request import urlopen # grabs a page's HTML

from bs4 import BeautifulSoup # creates a navigable parse tree from the HTML
from bs4 import SoupStrainer
import jinja2 as jin # templating engine
from rich import print # for pretty CLI
from rich.padding import Padding
from rich.panel import Panel

# Section docstring, if necessary later
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


# Get taxon rank and name text from breadcrumbs
def get_taxon(soup) -> tuple:
    """Returns (taxon_rank : str, taxon_name : str) based on the first set of breadcrumbs encountered

    Taxon rank is lowercased and comes from the link's title attribute. Some BugGuide categories are non-taxonomic (e.g. "unidentified larvae" or "mostly pale spp") and use title="No Taxon", in which case this function returns "section" for taxon_rank
    """
    taxon_tag = soup.find(class_="bgpage-roots").find_all("a")[-1]
    taxon_rank = taxon_tag['title'].lower() if taxon_tag['title'] != 'No Taxon' else 'section'
    taxon = taxon_tag.get_text()
    return taxon_rank, taxon


# Log results for one processed record to the terminal
def log_comments(comms: list, src, type="import") -> None:
    """Print an update to the terminal for this set of comments"""
    if comms == None:
        return

    # Log action being taken
    s = 's' if len(comms) != 1 else ''
    if type == "skip":
        print(f"> [i]Skipping {len(comms)} comment{s} from {src}")
    elif type == "screen":
        print(f"> {len(comms)} comment{s} found on {src}")
    elif type != "import":
        raise ValueError("Log type must be in ['import', 'skip', 'screen']")

    # In verbose mode, also log the comment text
    if args.verbose or type == "screen":
        if type == "skip":
            border = "dim cyan"
            style = "dim cyan i"
        else:
            border = "cyan"
            style = "none"
        
        for c in comms:
            body = re.sub("<[^<]+?>", "", c['body'])
            subject = re.sub("<[^<]+?>", "", c['subj'])
            byline = re.sub("<[^<]+?>", "", c['byline'])
            print(Padding(Panel(body, 
                                title=subject, title_align="left", 
                                subtitle=byline, subtitle_align="left", 
                                style=style, border_style=border), (1,4,0,4)))
        print(" ")


def screen_record(rec):
    log_comments(rec['comments'], rec['url'], "screen")
    # Prompt user
    print("[bold]Export associated record?[/bold]\n"
            "    [b cyan]y[/b cyan] -> [b cyan]yes[/b cyan]\n"
            "    [b cyan]n[/b cyan] -> [b cyan]no[/b cyan]\n"
            "    [b cyan]a[/b cyan] -> [b cyan]auto[/b cyan]-export remaining records\n"
            "    [b cyan]q[/b cyan] -> skip remaining records and [b cyan]quit[/b cyan] \n>>> ", end="")
    cmd = input().strip().lower()
    while cmd not in ['y', 'yes', 'n', 'no', 'a', 'auto', 'q', 'quit']:
        print("[magenta]Command not recognized — please enter one of the options above[/magenta] \n>>> ", end="")
        cmd = input().strip().lower()
    print(" ")
    if cmd[0] == 'y':
        print(f"> [i]Exporting {len(rec['comments'])} comment{'s' if len(rec['comments']) != 1 else ''}")
        return rec
    elif cmd[0] == 'n':
        print("> [i]Record skipped")
        return None
    elif cmd[0] == 'a':
        args.screen = False
        args.verbose = False
    else:
        exit()


# Process the comments from one record for export, according to user options
def filter_record(rec):
    if not rec['comments']:
        print("> No comments found at", rec['url'])
        return None

    # Add some styling metadata to the comment
    for c in rec['comments']:
        # Skip subject lines where the user didn't provide one so BG just filled it with body text
        if c['body'][:len(c['subj'])] == c['subj']:
            c['subj'] = ''
        # Highlight comments that have text other than (or in addition to) "Moved from ___"
        c['highlight'] = not re.match('Moved from .+\.\s*$', c['body'], flags=re.I)

    # Filter record and/or specific comments based on comment content and user args
    if args.ignore_moves:
        marked, unmarked = [], []
        for c in rec['comments']:
            if c['highlight']: marked.append(c)
            else: unmarked.append(c)
        # If none are highlighted, discard the record
        if not marked:
            log_comments(rec['comments'], rec['url'], "skip")
            return None
        if args.ignore_moves == "always":
            # If skipping all move comments, only keep highlighted comments
            if unmarked:
                log_comments(unmarked, rec['url'], "skip")
            rec['comments'] = marked
    
    # Manual screen after filtering, if applicable
    if args.screen:
        screen_record(rec)

    log_comments(rec['comments'], rec['url'])
    return rec


def parse_comment(ctag) -> dict:
    """Returns extracted HTML text for a single comment on a record page
    
    Dict keys
    -------------------
    'subj' : str
    'body' : str
    'byline' : str
        Unicode string contents of div.comment-subject, div.comment-body, and div.comment-byline
    'depth' : int
        How many levels deep this comment was in the reply hierarchy
    """
    cdict = {}
    cdict['subj'] = ctag.find(class_="comment-subject").decode_contents().strip()
    cdict['body'] = ctag.find(class_="comment-body").decode_contents().strip()
    cdict['byline'] = ctag.find(class_="comment-byline").decode_contents().strip()
    # Nested reply depth — replies are wrapped in the second td of a table, and use the first td's width to create 25px-unit indents
    if ctag.parent.name == 'td':
        cdict['depth'] = int(ctag.parent.previous_sibling['width']) // 25
    else: 
        cdict['depth'] = 0
    return cdict


def parse_record(soup) -> dict:
    """Returns all data of interest from the page for a BugGuide image submission
    
    Dict keys
    -------------------
    'url' : str
        URL for the page this data corresponds to
    'img' : str
        URL for the image
    'title' : str
        User-provided image title, taxon name, and/or creature sex(es); taxon name is always present, the other two are optional
    'metadata' : str
        Location, date, and/or size; if all are absent (rare but possible), this value will be an empty string
    'remarks' : str
        User-provided general description; often absent
    'byline' : str
        Username, upload date, and last edited date; first two parts are always present
    'comments' : list : Comment
        All comments that appear on this page, in display order (i.e. reverse chrono with nested replies)
    """

    rdict = {}
    # Infer the page URL — .bgimage-id contains the text "Photo#[number]", which is the same ID number used by the record's URL
    url_node = int(soup.find(class_="bgimage-id").get_text()[6:])
    rdict['url'] = f"https://bugguide.net/node/view/{url_node}"
    rdict['img'] = soup.find(class_="bgimage-image")["src"]
    # If one or both M/F symbols are present in title, replace symbol gif with text before decoding the Tag object
    title_tag = copy(soup.find(class_="node-title"))
    symbols = title_tag.find_all("img")
    if symbols:
        # The images have "Male"/"Female" alt text
        title_tag.append(symbols[0]['alt'].lower())
        title_tag.img.decompose()
        if len(symbols) == 2:
            title_tag.append(' & ' + symbols[1]['alt'].lower())
            title_tag.img.decompose()
    rdict['title'] = title_tag.decode_contents().strip()
    # div.bgimage-where-when element is reliably present, even if it's empty
    rdict['metadata'] = soup.find(class_="bgimage-where-when").decode_contents().strip()
    # div.node-body element is absent if the user provided no description
    node_body = soup.find(class_="node-body")
    rdict['remarks'] = node_body and node_body.decode_contents().strip() or ''
    # div.node-byline
    rdict['byline'] = soup.find(class_="node-byline").decode_contents().strip()

    # List of comments
    rdict['comments'] = [parse_comment(c) for c in soup.find_all(class_="comment")]

    return rdict


def make_soup(url: str) -> BeautifulSoup:
    # print("Making soup from", url)
    html = urlopen(url).read().decode("utf-8")
    return BeautifulSoup(html, "html.parser", parse_only=SoupStrainer(class_="col2"))


# Process sections within a single page
def process_list_page(soup, src: str, all_sections: list) -> None:
    # Check the pager for current page number
    try:
        page = soup.find(class_="pager").find("b").get_text()
    except AttributeError: 
        # (Single-page results don't have a pager)
        page = "1"
    
    # Pull the page sections that have image links in them
    page_sections = soup.select(".node-main, .node-main-alt")
    for sec_soup in page_sections:
        # Log progress to console
        rank, taxon = get_taxon(sec_soup)
        # Italicize genera, species, and subspecies
        if re.match('genus|species', rank):
            rich_taxon = '[i]' + taxon + '[/i]'
            taxon = '<i>' + taxon + '</i>'
        else: 
            rich_taxon = taxon
        print(f"--------\nScanning page {page} submissions for '{rich_taxon}'...\n--------")

        # Check if this section represents a new taxon or another chunk of the previous section
        breadcrumbs_text = sec_soup.find(class_="bgpage-roots").get_text()
        if not all_sections or breadcrumbs_text != all_sections[-1]['title']:
            # Last link in section breadcrumbs = this taxon's own record list
            taxon_url = sec_soup.find(class_="bgpage-roots").find_all("a")[-1]["href"]
            # Current url = position in parent's record list
            # Start a new section
            secdict = dict(title=breadcrumbs_text, rank=rank, taxon=taxon,
                           own_page=taxon_url, parent_page=src, records=[])
            all_sections.append(secdict)
        
        for item in sec_soup.find_all("a", recursive=False):
            record_url = item.get('href')
            print(f"Checking [i cyan]{record_url}")
            sleep(9)

            soup = make_soup(record_url)
            record = parse_record(soup)
            all_sections[-1]['records'].append(record)
            
            if not record['comments']:
                print("> No comments found")
            else:
                if args.verbose:
                    log_comments(record['comments'], record['url'])
                else:
                    ncom = len(record['comments'])
                    print(f"Saved {ncom} comment{'s' if ncom != 1 else ''}")
            
            args.imgcount -= 1
            if args.imgcount == 0:
                exit(0)


# Return a probably-okay URL or die trying
def check_url(url: str) -> str:
    """
    Does some basic checks on the user-provided URL string, and asks the user for a new URL if it fails, returning whatever succeeds
    
    If a user provides a URL that is a BugGuide page and is associated with a particular taxon, but is for the wrong section of its guide, will return a corrected version of that URL
    """
    
    while True:
        try:
            # TODO: Does this even look like a URL?

            # Is this from the Secret Beta Version?
            if "beta.bugguide.net" in url:
                raise RuntimeError("Sorry, scanning the beta site is unsupported")

            # Is this obviously not a BugGuide URL?
            if "bugguide.net" not in url:
                raise RuntimeError("Hey, this isn't BugGuide!")

            # Is this a BugGuide URL but obviously not part of the guide?
            if not re.search("bugguide\.net/node/view/\d+", url):
                raise RuntimeError("Oops, this isn't a guide page!")

            # Is this a URL for one of the other Guide tabs? (excluding "Info," which has no suffix and so can't be identified by URL alone)
            wrong_tab = re.search("bugguide\.net/node/view/\d+/(tree|bgpage|bglink|bgref|data)", url)
            if wrong_tab:
                # If so, it can be corrected without fetching the wrong page first
                url = url[:wrong_tab.start(1)] + "bgimage"
                print(f"Not an images page, adjusting URL to {url} ...")
                sleep(3)

            return url
        
        except RuntimeError as e:
            print("[magenta]" + str(e))
            url = input("Please enter another URL >>> ")


# Return some okay soup or die trying
def check_soup(soup) -> BeautifulSoup:
    """
    Checks that this is the right kind of BugGuide page, i.e. part of the images list for a particular taxon/group, and asks the user for a new URL if not
    
    If a user provides a URL for the Info tab of a particular taxon, will navigate to the start of the images list and return the soup for that instead
    """
    while True:
        try:
            # The "Taxonomy-Browse-Info-Images-Links-Books-Data" tabs are only visible when in the Guide
            menubar = soup.find(class_="guide-menubar")

            # check_url should catch the most egregious of the BugGuide-but-not-guide URLs, but as a backup check, menubar element is either absent or present but empty on non-guide pages
            if not menubar or not menubar.get_text():
                raise RuntimeError("Oops, this isn't a guide page!")
            
            # If current tab is "Images", great, we're all set
            img_tab = menubar.find(string="Images").parent
            if img_tab.name != 'a' and img_tab['class'].count("guide-menubar-selected"):
                return soup
            
            # Unexpected URLs that made it this far are part of the guide for a specific taxon, just the wrong part; find the associated correct URL and use that
            correct_url = img_tab["href"]

            # Pull the taxon name from the page breadcrumbs for more helpful error messaging, since we're already here
            rank, taxon = get_taxon(soup)
            if 'genus' in rank or 'species' in rank:
                taxon = '[i]' + taxon + '[/i]'

            # If no tab is currently selected, this is an individual record page
            if not menubar.find(class_="guide-menubar-selected"):
                print(f"URL is for a record in {rank} [b]{taxon}[/b]")
            # Otherwise some other tab (i.e. "Info") is selected
            else:
                print(f"URL is for another guide page in {rank} [b]{taxon}[/b]")
            
            print(f"Fetching all images for [b]{taxon}[/b] from {correct_url} ...")

            sleep(9)
            return make_soup(correct_url)
        
        except RuntimeError as e:
            print("[magenta]" + str(e))
            url = check_url(input("Please enter another URL >>> "))


# TODO: add pgcount and imgcount args!
# (valid args so far: --url, --verbose)
def import_taxon():
    # TODO: More informative prompt text

    if not args.url:
        print("[bold]Start checking image comments on: ", end="")
        args.url = input()
    url = check_url(args.url)
    soup = make_soup(url)
    rank, taxon = get_taxon(soup)

    # TODO: appendable files?
    if not exists('data'):
        mkdir('data')
    file_name = taxon
    # Avoid overwriting files unless explicitly told to
    if not args.replace:
        ver = 1
        vername = file_name
        while exists("data/"+vername+".json"):
            vername = f"{file_name} ({ver})"
            ver += 1
        file_name = vername
    file_name = "data/"+file_name+".json"

    dtstamp = dt.isoformat(dt.now(), ' ', 'seconds')
    context = dict(snapshot_date=dtstamp, header='', parent_rank=rank, start_url=url, sections=[])

    # TODO: error handling for write permissions failure?
    # TODO: more graceful handling of KeyboardInterrupt
    with open(file_name, "w", encoding="utf-8") as f:
        try:
            # While there's still pages of results to fetch:
            while url:    
                if not context["sections"]:
                    # Start of loop, so add the page header to context
                    title_tag = soup.find(class_="node-title")
                    # (The template needs both plaintext and italics, and Jinja doesn't want to regex within the template)
                    context["header"] = dict(html=title_tag.h1.decode_contents(), plain=title_tag.get_text())
                else:
                    # Not the start of the loop, so make new soup
                    soup = make_soup(url)
                # Do this page
                process_list_page(soup, url, context["sections"])
                # Check if this is enough pages
                args.pgcount -= 1
                if args.pgcount == 0:
                    exit(0)
                # Check if there's another page to do
                next_arrow = soup.find(alt="next page")
                url = next_arrow and next_arrow.parent.get('href')
        finally:
            json.dump(context, f, indent=4)
            # Reprint file name for ease of reference
            print(f"\nResults saved to '{file_name}'")


# TODO: add chrono arg!
# (much function, very placeholder)
def export_taxon():
    # Check for the given taxon name
    fname_in = f"data/{args.taxon}.json"

    # TODO: actual error handling
    if not exists(fname_in):
        print('uh oh...')
    
    with open(fname_in, "r", encoding="utf-8") as fin:
        context = json.load(fin)
    
    if not exists('comments'):
        mkdir('comments')
    
    # Pick an output file name
    # TODO: file path validation?
    fname_out = args.fname or args.taxon

    # Avoid overwriting files unless explicitly told to
    if not args.replace:
        ver = 1
        vername = fname_out
        while exists("comments/"+vername+".html"):
            vername = f"{fname_out} ({ver})"
            ver += 1
        fname_out = vername
    fname_out = "comments/"+fname_out+".html"

    # Set up html template and process the records
    env = jin.Environment(loader=jin.FileSystemLoader("templates/"))
    template = env.get_template("comments.html")
    with open(fname_out, "w", encoding="utf-8") as fout:
        try:
            for sec_idx, sec in enumerate(context['sections']):
                filtered = []
                for rec in sec['records']:
                    try:
                        r = filter_record(rec)
                        if r:
                            filtered.append(r)
                    except (RuntimeError, SystemExit) as e:
                        # Only what's been successfully filtered should get exported
                        if filtered:
                            sec['records'] = filtered
                            context['sections'] = context['sections'][:sec_idx+1]
                        else:
                            context['sections'] = context['sections'][:sec_idx]
                        raise
                # Drop records that didn't pass screening
                sec['records'] = filtered
        finally:
            # Always write to file, even if stopped by an error
            fout.write(template.render(context))


# Print some summary info about the .json files that have been generated so far
def list_snapshots():
    snapfiles = sorted(glob('data/*.json'))
    for fname in snapfiles:
        with open(fname, 'r') as f:
            snap = json.load(f)

        title = "Snapshot: [b]" + fname
        body = "[b cyan]" + snap['header']['plain'] + "[/b cyan]\n\n"
        body += f"[cyan][b]Start point on[/b] {snap['snapshot_date']}:[/cyan] {snap['start_url']}\n"

        sections = {}
        total_recs = recs_with_comments = 0
        for sec in snap['sections']:
            name = sec['rank'] + " " + sec['taxon']
            sections[name] = {'first': sec['records'][0]['url'], 
                              'last': sec['records'][-1]['url']}
            total_recs += len(sec['records'])
            recs_with_comments += len([1 for r in sec['records'] if r['comments']])
        body += f"{total_recs} total records scanned (about {ceil(total_recs/24)} pages), {recs_with_comments} with comments\n\n"
        body += "[b cyan]Sections:[/b cyan]"
        for name, urls in sections.items():
            body += f"\n* {name}" \
                 + f"\n   -  [cyan]Most recent record:[/cyan] {urls['first']}" \
                 + f"\n   -  [cyan]Oldest record:[/cyan]      {urls['last']}"
        
        print(Padding(Panel(body, title=title, title_align="left",
                            border_style="none", highlight=True), (1,4,0,4)))


# Args and parser definition
def argparser() -> ArgumentParser:
    # TODO: EDIT ALL OF THIS
    desc = "Scans BugGuide's user submissions under a particular species or other taxon, and collects submission comments that might have interesting discussions or identification tips.\nAll records encountered during import have their metadata saved as a JSON file, if you have other scripts you might want to process that data with, but the built-in export options assume that you're only interested in records with comments that match the given set of filters."
    parser = ArgumentParser(description=desc)

    subparsers = parser.add_subparsers(dest='action', title='tasks')

    # IMPORT
    importer = subparsers.add_parser('import', help='download record data for taxon')
    importer.set_defaults(func=import_taxon)
    # -u, --url [url]
    importer.add_argument('-u', '--url',
                          help='starting URL; must be associated with the guide for a specific taxon; if this doesn\'t link directly into the guide\'s image list, it will find the associated image list and start on page 1')
    # --pgcount | --imgcount
    importer.add_argument('-p', '--pgcount', type=int, default=-1,
                          help='stop after checking this many pages in the Images tab')
    importer.add_argument('-i', '--imgcount', type=int, default=-1,
                          help='stop after checking this many images')
    # -r, --replace
    importer.add_argument('-r', '--replace', action="store_true",
                        help='overwrite existing data for this taxon')
    # -v, --verbose
    importer.add_argument('-v', '--verbose', action="store_true",
                          help='print comment text as comments are encountered')

    # EXPORT
    exporter = subparsers.add_parser('export', help='export previously-imported snapshot of taxon records to file')
    exporter.set_defaults(func=export_taxon)
    # TODO: what are we exporting
    # taxon (positional arg)
    exporter.add_argument('taxon',
                         help='')
    # --screen
    exporter.add_argument('--screen', action="store_true",
                        help='interactive mode: print each set of comments found and ask for user approval before exporting them')
    # -i, --ignore-moves ['always' or 'nochat']
    exporter.add_argument('--ignore-moves', choices=['always', 'nochat'],
                        help='skip auto-generated move comments from editors ("Moved from Potter and Mason Wasps.") unless the editor added additional commentary to the body text; "nochat" only skips if *all* of the comments are move comments, to preserve conversational context about misclassifications')
    # --fname [filename]
    exporter.add_argument('--fname',
                        help='name for .html output file; otherwises uses taxon name')
    # -r, --replace
    exporter.add_argument('-r', '--replace', action="store_true",
                        help='if a file with this name already exists, overwrite it')
    # -v, --verbose
    exporter.add_argument('-v', '--verbose', action="store_true",
                          help='print comment text as comments are encountered')

    # BROWSE
    browser = subparsers.add_parser('list', help='print details about what you\'ve downloaded so far')
    browser.set_defaults(func=list_snapshots)

    return parser


if __name__ == '__main__':
    global args
    args = argparser().parse_args()
    args.func()
    
