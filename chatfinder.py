from argparse import ArgumentParser # for CL args
from html import unescape
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
import rich.repr


class Comment:
    """Container for extracted HTML text and some simple style markers from a single comment on a record page
    
    Instance attributes
    -------------------
    data : dict
        Unicode string representation of the contents of div.comment-subject, div.comment-body, and div.comment-byline
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
            How much to indent a nested reply comment; converts BugGuide's 25px indent increments to multiples of 2rem
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
    """Container for data of interest from the page for a BugGuide image submission
    
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



    