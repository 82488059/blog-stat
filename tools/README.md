# tools/ (local only)

Offline helpers for a Hexo blog tree (image/ref health reports, CSDN URL cleanup).

**Warning**

- These scripts are **not** part of the FastAPI stats service and are **not** served by uvicorn.
- Some scripts (e.g. `clean_csdn_image_urls.py`) **write** to markdown under a blog `source/_posts` path.
- Paths may be hard-coded to a local blog checkout (e.g. `e:/myblog/blog`). Adjust before running.
- Run only on a trusted workstation. **Do not** expose this directory on a public host or hang it behind nginx.

Typical use: copy or point at your blog repo, run with the local venv Python, inspect JSON reports, commit blog changes from the blog repo — not from this stats repo.
