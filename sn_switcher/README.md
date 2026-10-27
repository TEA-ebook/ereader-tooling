# sn_switcher

Writes the selected serial to `~/qboo/private/prod/sn`.

```sh
sn_switcher.sh                # interactive menu (arrows/j/k, Enter to apply, q to quit)
sn_switcher.sh my-reader      # apply by name or line number
sn_switcher.sh -c other.conf  # use another config (or set SN_CONFIG)
```

Config: `~/qboo/serials.conf`, a CSV with the header `name,serial`. See [`serials.conf.example`](serials.conf.example).
