# Circular DfMA — Streamlit interface

A public-hostable counterpart to `python -m cdfma.gui` (the Tkinter
desktop GUI). Same six sections — Legend, Findings, Option comparison,
Gap report, Add material, Add connection — built on the exact same
`cdfma` package (`src/cdfma`, unchanged) that the CLI and Tkinter GUI use.
See [`app.py`](app.py)'s module docstring for why this lives in its own
folder rather than inside `src/cdfma`.

## Run locally

From the repo root:

```
python -m pip install -r streamlit_app/requirements.txt
streamlit run streamlit_app/app.py
```

It defaults to this repo's own `data/` directory and
`data/project_wall.yaml`, editable in the sidebar.

## Deploy on Streamlit Community Cloud (free, public)

1. Push this repo to GitHub (it must be public, or your Streamlit Cloud
   plan must support private repos).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in
   with GitHub.
3. **New app** → pick this repository and branch.
4. **Main file path**: `streamlit_app/app.py`
5. Under **Advanced settings**, confirm the **Python dependencies file**
   resolves to `streamlit_app/requirements.txt` (Streamlit Cloud checks
   the main file's own directory first, so this is usually automatic).
6. Deploy. Streamlit Cloud gives you a `*.streamlit.app` URL, shareable
   with anyone.

*I can't create this deployment myself from this environment (no access
to your Streamlit/GitHub credentials) — the steps above are for you to
run once this folder is pushed.*

## Persistence caveat

**"Add material" and "Add connection" write to `data/*.yaml` inside the
running container's filesystem.** On Streamlit Community Cloud that
filesystem is ephemeral: writes are visible to everyone using that same
running instance, but are lost on redeploy, reboot, or a new container
spin-up, and are never committed back to the GitHub repo. Treat the
hosted app's write capability as a scratchpad for trying out a new
material/connection, not a way to permanently extend the library —
for that, edit `data/*.yaml` locally (or use the two "Add" tabs when
running locally) and commit the result.
