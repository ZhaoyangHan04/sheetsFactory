"""Native N720 schema, identical to the frozen pure-probe public contract."""
from . import adapter
exec(compile(adapter.adapted_ast('spec'),__file__,'exec'),globals())
SPEC_KIND=adapter.SPEC_KIND
SPEC_VERSION=3
PRODUCTION_COUNTS=dict(zip(('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource','region_exposure','sector_exposure','exclusivity','prerequisite'),(1,60,60,360,120,160,120,240)))
PRODUCTION_ROW_COUNT=1121
