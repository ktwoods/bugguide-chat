import re

from rich.padding import Padding
from rich.panel import Panel
from rich import print


# Log results for one processed record to the terminal
def log_comments(comms: list, src: str, type="import", verbose=False) -> None:
    """Print an update to the terminal for this set of comments"""
    if not comms:
        return

    # Log action being taken
    s = 's' if len(comms) != 1 else ''
    if type == "skip":
        print(f"> [i]Skipping {len(comms)} comment{s} from {src}")
    elif type == "screen":
        print(f"> {len(comms)} comment{s} found on {src}")
    elif type == "import":
        print(f"> Saved {len(comms)} comment{s}")
    else:
        raise ValueError("Log type must be in ['import', 'skip', 'screen']")

    # In verbose mode, also log the comment text
    if verbose or type == "screen":
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
