from copy import copy
from datetime import datetime as dt # for timestamping imports
import json
from math import ceil
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir
import re
from time import sleep # enforces crawl-delay
from urllib.request import urlopen # grabs a page's HTML

from bs4 import BeautifulSoup # creates a navigable parse tree from the HTML
from bs4 import SoupStrainer
from rich import print
from rich.prompt import Prompt, IntPrompt, Confirm, InvalidResponse

from helper import *


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
                log_comments(record['comments'], record['url'], verbose=args.verbose)
            
            args.imgcount -= 1
            if args.imgcount == 0:
                exit(0)


def validate_page(soup):
    # The "Taxonomy-Browse-Info-Images-Links-Books-Data" tabs are only visible when in the Guide (otherwise the menubar element is either absent or present but empty)
    menubar = soup.find(class_="guide-menubar")
    if not menubar or not menubar.get_text():
        raise InvalidResponse("[magenta]Hmm, this doesn't look like a guide page!\nI need a starting point in the Images tab for a particular type of bug — something that looks like this: 'https://bugguide.net/node/view/9137/bgimage'")
    
    # If current tab is "Images", great, we're all set
    img_tab = menubar.find(string="Images").parent
    if img_tab.name != 'a' and img_tab['class'].count("guide-menubar-selected"):
        return soup
    
    # Any unexpected URLs that made it this far are part of the guide for a specific taxon, just the wrong part

    # Pull the taxon name from the page breadcrumbs for more specific error messaging, since we're already here
    rank, taxon = get_taxon(soup)
    if 'genus' in rank or 'species' in rank:
        taxon = '[i]' + taxon + '[/i]'

    # If no tab is currently selected, this is an individual record page
    if not menubar.find(class_="guide-menubar-selected"):
        print(f"URL is for a record in {rank} [b]{taxon}[/b]")
    # Otherwise some other tab (i.e. "Info") is selected
    else:
        print(f"URL is for another guide page in {rank} [b]{taxon}[/b]")
    
    correct_url = img_tab["href"]
    confirm = Confirm.ask(f"Do you want me to start on page 1 of the images for this taxon? ({correct_url})")
    if confirm:
        return make_soup(correct_url)
    return None


class URLPrompt(Prompt):
    def process_response(self, url: str):
        url = url.strip()
        if url in ['q', 'quit', 'exit']:
            exit(0)

        # Is this obviously not a BugGuide URL?
        if "bugguide.net" not in url:
            raise InvalidResponse("[magenta i]This doesn't look like BugGuide!")

        # Is this from the Secret Beta Site?
        if "beta.bugguide.net" in url:
            url = url.replace("beta.", "")
            print(f"[magenta i]Sorry, I don't know how to read the beta site; switching to '{url}' ...")

        # Is this a BugGuide URL but not part of the Guide™?
        if not re.search("bugguide\.net/node/view/\d+", url):
            raise InvalidResponse("[magenta][i]This doesn't look like a guide page![/i] I need a starting point in the Images tab for a particular type of bug — something that looks like this: 'https://bugguide.net/node/view/9137/bgimage'")

        # Is this a URL for one of the other Guide tabs? (excluding "Info," which has no suffix and so can't be identified by URL alone)
        wrong_tab = re.search("bugguide\.net/node/view/\d+/(tree|bgpage|bglink|bgref|data)", url)
        if wrong_tab:
            # If so, it can be corrected without fetching the wrong page first
            url = url[:wrong_tab.start(1)] + "bgimage"
            print(f"[magenta i]This doesn't look like a page with photos, let's try {url} ...")

        # The rest of potential parsing errors have to be checked against the actual page
        try:
            soup = make_soup(url)
        except Exception as err:
            raise InvalidResponse("[magenta][i]I ran into a problem loading this page: [/i]" + err.args[0])

        soup = validate_page(soup)
        if not soup: # User wants to try a different URL
            raise InvalidResponse("") # Keep going with the prompt loop

        return url, soup


class PosIntPrompt(IntPrompt):
    validate_error_message = "[magenta]Please enter a valid number"

    def process_response(self, value: str):
        value = super().process_response(value)
        if value <= 0:
            raise InvalidResponse("[magenta]Number needs to be greater than 0")
        return value


def import_taxon(cfg):
    global args
    args = cfg
    setup = True if not args.url else False
    PG_THRESHOLD = 20
    
    if setup:
        url, soup = URLPrompt.ask("[b]Enter a URL to start searching on[/b] (or enter \"q\" to quit)")
    else:
        url = args.url
        soup = validate_page(make_soup(url))

    rank, taxon = get_taxon(soup)
    # Check page's pager
    pager = soup.find(class_="pager")
    if not pager: # First and only page
        tot_pages = start = 1
    elif len(pager.contents) != 5: # Last (but not only) page
        tot_pages = start = pager.contents[2].find("b").get_text()
    else:
        start = pager.contents[2].find("b").get_text()
        pager_end = pager.contents[-1].a
        if pager_end: # Somewhere in the middle, final page num may not be visible
            end_url = pager.get("href")
            end_count = int(re.search("(from=)(\d+)$", end_url).group(2))
            tot_pages = ceil(end_count / 24 + 1)
        else: # On the last page
            tot_pages = start
    
    print(f"Found {tot_pages} total pages for '{taxon}' (starting on page {start})")
    confirm = Confirm.ask("Continue?")
    if not confirm:
        exit(0)

    if setup:
        print(f"Limit results by:\n  1 = number of images\n  2 = number of pages\n  3 = neither (default is {PG_THRESHOLD} pages)")
        limit = Prompt.ask("", choices=["1", "2", "3", "q"], default="3", show_default=False)
        if limit == "q":
            exit(0)
        elif limit == "1":
            args.imgcount = PosIntPrompt.ask("Check this many images (24 photos per page)")
        elif limit == "2":
            args.pgcount = PosIntPrompt.ask("Check this many pages of results")
        if args.pgcount > PG_THRESHOLD or args.imgcount > 24 * PG_THRESHOLD:
            confirm = Confirm.ask(f"This is more than {PG_THRESHOLD} pages of results. The search speed will get much slower after {PG_THRESHOLD} pages. Do you want to continue?")
            if not confirm:
                exit(0)
        
        args.replace = Confirm.ask("Overwrite any previous files for this taxon?")
        args.verbose = Confirm.ask("Print comment text here as I go?")
        print(f"Starting search! To repeat this search without going through setup, use:",
              f"\n\t[cyan]bgc import -u {url}",
              f"{'-p ' + str(args.pgcount) if args.pgcount != -1 else ''}",
              f"{'-i ' + str(args.imgcount) if args.imgcount != -1 else ''}",
              f"{'-v' if args.verbose else ''} {'-r' if args.replace else ''}")

    imgcap = args.imgcount
    pgcap = args.pgcount
    
    if not exists('../data'):
        mkdir('../data')
    file_name = taxon
    # Avoid overwriting files unless explicitly told to
    if not args.replace:
        ver = 1
        vername = file_name
        while exists("../data/"+vername+".json"):
            vername = f"{file_name} ({ver})"
            ver += 1
        file_name = vername
    file_name = "../data/"+file_name+".json"

    dtstamp = dt.isoformat(dt.now(), ' ', 'seconds')
    context = dict(snapshot_date=dtstamp, header='', parent_rank=rank, start_url=url, sections=[])

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
        except KeyboardInterrupt:
            print("\n[magenta]Ending scan...")
        # except Exception as e:
            # print("\n[magenta]Error encountered:", e.args)
        finally:
            json.dump(context, f, indent=4)
            # Print reason for finishing
            if not args.imgcount:
                print(f"\nFinished checking {imgcap} image{'s' if imgcap != 1 else ''}!")
            elif not args.pgcount:
                print(f"\nFinished checking {pgcap} page{'s' if pgcap != 1 else ''}!")
            elif not url:
                print("\nReached end of list!")
            # Reprint file name for ease of reference
            print(f"Results saved to '{file_name}'")

