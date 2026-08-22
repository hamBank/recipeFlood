# `data/images/`

Empty in git, on purpose.

`scripts/fetch_images.py` downloads the images from the imported blog posts
into this directory and writes an `index.json` mapping each post URL to its
file. `scripts/load_snapshot.py --with-images` then copies them into the
app's upload directory.

**The files themselves are not committed.** The source blog has 44 posts
with an image, and not one of them is the blog's own photo — every one is a
hotlink to a commercial recipe site (goodfood.com.au, taste.com.au, ABC,
BBC Good Food, Yahoo). Twelve years on, 40 of the 44 no longer resolve; the
four that do are someone else's press photography. Since this repository
and the site it deploys are both public, committing them would republish
them, which is a licensing decision rather than a technical one.

So: the pipeline is here and works, and it is off by default. Imported
recipes keep `image_source_url` for provenance and show a generated
placeholder tile. To use the images anyway:

```bash
python scripts/fetch_images.py
python -m scripts.load_snapshot --with-images
```

The better answer is your own photos — the recipe form has an upload field,
and `POST /recipes/{key}/image` backs it.
