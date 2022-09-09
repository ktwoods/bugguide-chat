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

