import json
from math import ceil
from glob import glob

from rich.padding import Padding
from rich.panel import Panel
from rich import print

# Print some summary info about the .json files that have been generated so far
def list_snapshots(args):
    snapfiles = sorted(glob('../data/*.json'))
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
            total_recs += len(sec['records'])
            if total_recs:
                sections[name] = {'first': sec['records'][0]['url'], 
                                'last': sec['records'][-1]['url']}
                recs_with_comments += len([1 for r in sec['records'] if r['comments']])
        
        pages = ceil(total_recs/24)
        body += f"{total_recs} total record{'s' if total_recs != 1 else ''} scanned " \
              + f"(about {pages} page{'s' if pages != 1 else ''}), " \
              + f"{recs_with_comments} with comments\n\n"
        
        body += "[b cyan]Sections:[/b cyan]"
        for name, urls in sections.items():
            body += f"\n* {name}" \
                  + f"\n   -  [cyan]Most recent record:[/cyan] {urls['first']}" \
                  + f"\n   -  [cyan]Oldest record:[/cyan]      {urls['last']}"
        
        print(Padding(Panel(body, title=title, title_align="left",
                            border_style="none", highlight=True), (1,4,0,4)))