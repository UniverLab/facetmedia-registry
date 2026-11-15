The runner inserts the Mermaid SVG at <!-- DIAGRAM --> in index.html,
decoding &gt; inside <style> and stripping xmlns attributes; build.mjs only
copies index.tmpl to index.html. No other media ships with this sample.
