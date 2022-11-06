from argparse import ArgumentParser # for CL args

from import_comments import *
from export_comments import *
from list import *


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
    importer.add_argument('url',
                          help='starting URL, which must be associated with the guide for a specific taxon (if this doesn\'t link directly into the guide\'s image list, it will find the associated image list and start on page 1)')
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
    args = argparser().parse_args()
    args.func(args)
    
