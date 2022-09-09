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

class Comment:
    def __init__(self, comment_tag: Tag):
        self.data = {}
        self.style = {}

        # data: Pull text sections
        self.data['subj'] = comment_tag.find(class_="comment-subject").decode_contents().strip()
        self.data['body'] = comment_tag.find(class_="comment-body").decode_contents().strip()
        self.data['byline'] = comment_tag.find(class_="comment-byline").decode_contents().strip()

        # metadata: If the user didn't give the comment a subject line, BG just replicates the start of the body text for it
        self.style['subj_repeats'] = self.data['body'][:len(self.data['subj'])] == self.data['subj']
        # metadata: Highlight if there's anything in this comment beyond just "Moved from ___"
        self.style['highlight'] = not re.match('Moved from .+\.\s*$', self.data['body'], flags=re.I)
        # metadata: Convert reply indent 
        if comment_tag.parent.name == 'td':
            # (replies are wrapped in the second td of a table, and use the first td's width as the indent)
            indent = int(comment_tag.parent.previous_sibling['width'])
            self.style['indent'] = indent // 25 * 2
        else: 
            self.style['indent'] = 0

