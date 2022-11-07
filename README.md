# \[WIP\] BugGuideChatter: a helper bot for finding comments on BugGuide
(* *Project name subject to change, I am terrible at naming things and have waffled between at least six versions already*)


BugGuide is a community-science gold mine for US & Canadian arthropod species — life history info, photos, range maps, discussions by knowledgeable experts, reference materials, and so forth. In *theory* each species and parent taxon has an info page in the Guide that includes tips on how to distinguish them from similar creatures, and some of the info pages are [painstakingly curated](https://bugguide.net/node/view/397), but there are just too many species and not enough BG editors, so sometimes the best place to find out how something is identified and what references the BG editors are using to do it is in the comments on submitted photos.

Unfortunately, there's no way to tell which of the photos have comments on them from a list [like this](https://bugguide.net/node/view/305704/bgimage) (and even if there was, a lot of the time they're just generic auto-comments generated when editors move things around)... which means that personally, in cases where I've been really dying to verify what something was, I spent way more time than I'm eager to admit clicking images, waiting for them to load, scrolling down to check for comments, copy-pasting any useful text and source URLs into my notes, hitting the back button to return to the image list, clicking on the next one, etc etc etc.

So instead I built a command-line app to do the clicking for me. And now I'm making it a bit bigger and adding a lot more dialogue text, so that it'll hopefully make sense to people who aren't just me.

My end goal is to publish a beta version on PyPI, shop it around a bit in search of feedback and bug reports, and then return to it for updates in early 2023 if it sounds like it is (or could be, with mods) useful to other people. The end version of this might not even be Python; it just happened to be a language I was working in at the time and wanted to learn how to do web scraping with.

