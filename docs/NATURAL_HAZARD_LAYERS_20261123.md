# Map hazard layers — engineering draft

The new Hazards menu provides a master switch and individual visibility controls for earthquake, tropical cyclone/hurricane, tornado, flood, tsunami, severe storm/wind, wildfire, volcano, winter weather, heat/drought, landslide/avalanche, and other disaster reports.

The menu also serves as the vector marker legend. Individual points and homogeneous clusters use distinct hazard glyphs; mixed clusters retain a neutral count and can be opened for source evidence. Severity colors, verification rings, provider coordinates, and official warning polygons retain their previous meaning. No fabricated point, forecast path, or current warning is inferred. Hiding a hazard removes its matching points, source rings, and warning areas from the displayed scope without altering collection, the archive, news category, or crisis stripes. The master preserves per-type preferences; reset restores all. Existing map_view preferences remain compatible.

USGS event type, GDACS event code, EONET category and NWS/CAP event fields supply finite display types. Legacy disaster records use conservative title/source recognition. Explicit non-earthquake USGS measurements remain other disaster reports, not quakes. Multi-type reports remain visible if any of their types is enabled. Mixed clusters do not misrepresent their constituent reports.

The controls apply within the existing archive filter/search/time and map display scope; they are not independent global weather data collectors or a live forecast/radar feed. No provider rights or data-source changes. Offline regression coverage only until actual Windows package and desktop checks pass. No release/merge authority.
