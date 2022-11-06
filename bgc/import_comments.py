from copy import copy
from datetime import datetime as dt # for timestamping imports
import json
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir
import re
from time import sleep # enforces crawl-delay
from urllib.request import urlopen # grabs a page's HTML

from bs4 import BeautifulSoup # creates a navigable parse tree from the HTML
from bs4 import SoupStrainer
from rich import print

from helper import *

global args

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
def import_taxon(cfg):
    # TODO: More informative prompt text
    args = cfg
    print(args)

    if not args.url:
        print("[bold]Start checking image comments on: ", end="")
        args.url = input()
    url = check_url(args.url)
    soup = make_soup(url)
    rank, taxon = get_taxon(soup)

    # TODO: appendable files?
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

