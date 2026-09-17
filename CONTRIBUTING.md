# Contributing

Report MOSAIC/OS/Python versions, input dimensions/dtype, pacing interval,
analysis range, bleaching settings, Status message, and reproduction steps.
Only attach data permitted for public sharing; remove personal paths.

For analysis, persistence, or timing changes, add a regression test and run:

```sh
python -m unittest discover -s tests -v
```

Numerical changes require a CHANGELOG entry. Compare accepted events and
measurements, not only averaged waveforms. Keep ND2 files, environments,
generated results, and unpublished documents out of Git. Preserve release tags
used for publications. Confirm license terms before contributing third-party
material.
