import json
from os.path import exists # for checking if this will overwrite an existing file
from os import mkdir

import jinja2 as jin # templating engine
from rich import print # for pretty CLI

from helper import *

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


# TODO: add chrono arg!
# (much function, very placeholder)
def export_taxon(args):
    # Check for the given taxon name
    fname_in = f"data/{args.taxon}.json"

    # TODO: actual error handling
    if not exists(fname_in):
        print('uh oh...')
    
    with open(fname_in, "r", encoding="utf-8") as fin:
        context = json.load(fin)
    
    if not exists('../comments'):
        mkdir('../comments')
    
    # Pick an output file name
    # TODO: file path validation?
    fname_out = args.fname or args.taxon

    # Avoid overwriting files unless explicitly told to
    if not args.replace:
        ver = 1
        vername = fname_out
        while exists("../comments/"+vername+".html"):
            vername = f"{fname_out} ({ver})"
            ver += 1
        fname_out = vername
    fname_out = "../comments/"+fname_out+".html"

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

