from pathlib import Path
from html import escape
from zipfile import ZipFile, ZIP_DEFLATED


OUT = Path("New/shopify_product_descriptions.docx")


PRODUCTS = [
    (1, "Midnight Clover Charm Bracelet", "gold-tone bracelet with glossy black clover charms", "black clover charms", "Charm Bracelet", "Clover / Floral", "Lobster Claw", "1"),
    (2, "Seaside Starfish Charm Bracelet", "chunky gold-tone chain bracelet with starfish, shell, and cowrie-inspired charms", "starfish and shell charms", "Charm Bracelet", "Coastal / Sea Life", "Lobster Claw", "1"),
    (3, "Golden Heart Station Bracelet", "delicate gold-tone bracelet with heart-shaped crystal stations and polished bead accents", "heart crystal stations", "Station Bracelet", "Heart / Minimal", "Lobster Claw", "1"),
    (4, "Vintage Coin Charm Bracelet", "gold-tone link bracelet with a vintage-inspired coin charm and polished chain detail", "coin charm", "Charm Bracelet", "Coin / Vintage", "Lobster Claw", "1"),
    (5, "Leopard Heart Tassel Bracelet", "braided textile bracelet with leopard print, pink embroidered hearts, and tassel ties", "pink heart embroidery", "Thread Bracelet", "Leopard / Heart", "Adjustable Tie", "1"),
    (6, "Crystal Station Bracelet", "minimal gold-tone bracelet with small crystal stations and a fine chain silhouette", "crystal accents", "Station Bracelet", "Minimal / Crystal", "Lobster Claw", "1"),
    (7, "Classic Crystal Tennis Bracelet", "sparkling tennis-style bracelet with a continuous row of clear stones", "clear crystal line", "Tennis Bracelet", "Classic / Crystal", "Foldover Clasp", "1"),
    (8, "Rainbow Crystal Tennis Bracelet", "gold-tone tennis bracelet finished with a colorful row of multicolor crystals", "multicolor crystals", "Tennis Bracelet", "Rainbow / Crystal", "Foldover Clasp", "1"),
    (9, "Aqua Crystal Tennis Bracelet", "silver-tone tennis bracelet with refreshing aqua-blue crystal detail", "aqua crystals", "Tennis Bracelet", "Aqua / Crystal", "Foldover Clasp", "1"),
    (10, "Sleek Pave Edge Bangle", "polished gold-tone bangle with a fine pave-style accent along the edge", "subtle crystal edge", "Bangle Bracelet", "Minimal / Pave", "Slip-On", "1"),
    (11, "Rainbow Crystal Open Cuff Bracelet", "gold-tone open cuff bracelet with a colorful crystal accent panel", "multicolor crystal panel", "Open Cuff Bracelet", "Rainbow / Crystal", "Open Cuff", "1"),
    (12, "Minimal Bar Open Bangle", "sleek gold-tone open bangle with a modern bar-style end detail", "bar accent", "Open Bangle", "Modern / Minimal", "Open Cuff", "1"),
    (13, "Studded Gold Bangle", "polished gold-tone bangle accented with evenly spaced stone-like studs", "round stud accents", "Bangle Bracelet", "Studded / Minimal", "Slip-On", "1"),
    (14, "Classic Plain Gold Bangle", "smooth gold-tone bangle with a clean, timeless polished finish", "plain polished finish", "Bangle Bracelet", "Classic / Minimal", "Slip-On", "1"),
    (15, "Rainbow Vine Open Cuff Bracelet", "sculptural gold-tone open cuff with organic curves and multicolor stones", "multicolor stones", "Open Cuff Bracelet", "Vine / Rainbow", "Open Cuff", "1"),
    (16, "Crystal Line Gold Bangle", "gold-tone bangle with a neat line of small sparkling crystals", "crystal line detail", "Bangle Bracelet", "Crystal / Classic", "Slip-On", "1"),
    (17, "Bamboo Link Gold Bangle", "gold-tone bangle with segmented bamboo-inspired link detailing", "bamboo-style texture", "Bangle Bracelet", "Bamboo / Link", "Slip-On", "1"),
    (18, "Trio Crystal Gold Ring", "gold-tone ring with a graceful trio of clear crystal accents", "three clear crystals", "Ring", "Trio / Crystal", "Ring Band", "1"),
    (19, "Infinity Bow Gold Ring", "gold-tone ring with a delicate infinity-bow inspired centerpiece", "infinity bow detail", "Ring", "Infinity / Bow", "Ring Band", "1"),
    (20, "Stacked Wave Open Cuff Bracelet", "bold gold-tone open cuff with layered wave-like bands", "layered wave bands", "Open Cuff Bracelet", "Stacked / Wave", "Open Cuff", "1"),
    (21, "Butterfly Charm Hoop Earrings", "gold-tone hoop earrings with sparkling butterfly and crystal drop charms", "butterfly and crystal drops", "Hoop Earrings", "Butterfly / Charm", "Hinged Hoop", "1 Pair"),
    (22, "Two-Tone Wave Stack Ring", "wide ring with layered silver-tone and gold-tone wave bands", "two-tone wave layers", "Ring", "Wave / Stacked", "Ring Band", "1"),
    (23, "Emerald Cut Bezel Ring", "gold-tone ring with a rectangular bezel-set crystal centerpiece", "emerald-cut crystal", "Ring", "Bezel / Crystal", "Ring Band", "1"),
    (24, "Sculptural Initial Ring", "gold-tone statement ring with a flowing initial-inspired script shape", "script initial design", "Ring", "Initial / Sculptural", "Ring Band", "1"),
    (25, "Emerald Bead Stack Ring", "gold-tone stacked bead ring accented with rich green stone details", "green stone accents", "Ring", "Stacked / Bead", "Ring Band", "1"),
    (26, "Faceted Heart Statement Ring", "gold-tone ring with a bold faceted heart centerpiece and beaded border", "faceted heart centerpiece", "Ring", "Heart / Statement", "Ring Band", "1"),
    (27, "Initial R Stud Earrings", "gold-tone stud earrings shaped with a sparkling letter R detail", "letter R motif", "Stud Earrings", "Initial / Letter", "Post Back", "1 Pair"),
    (28, "Initial P Stud Earrings", "gold-tone stud earrings shaped with a sparkling letter P detail", "letter P motif", "Stud Earrings", "Initial / Letter", "Post Back", "1 Pair"),
    (29, "Initial M Stud Earrings", "gold-tone stud earrings shaped with a sparkling letter M detail", "letter M motif", "Stud Earrings", "Initial / Letter", "Post Back", "1 Pair"),
    (30, "Crystal Teardrop Drop Earrings", "delicate gold-tone drop earrings with clear teardrop crystal pendants", "teardrop crystal drops", "Drop Earrings", "Teardrop / Crystal", "Hook / Drop", "1 Pair"),
    (31, "Layered Paperclip Chain Necklace", "gold-tone layered necklace with paperclip links and a sleek chain strand", "layered chain design", "Layered Necklace", "Paperclip / Layered", "Lobster Claw", "1"),
    (32, "Vintage Floral Medallion Necklace", "gold-tone pendant necklace with a round vintage floral medallion", "floral medallion pendant", "Pendant Necklace", "Floral / Vintage", "Lobster Claw", "1"),
    (33, "Minimal Solitaire Pendant Necklace", "delicate necklace with a small solitaire-style pendant on a fine chain", "solitaire pendant", "Pendant Necklace", "Minimal / Solitaire", "Lobster Claw", "1"),
    (34, "Crystal Heart Pendant Necklace", "gold-tone necklace with a sparkling heart-shaped pendant", "heart crystal pendant", "Pendant Necklace", "Heart / Crystal", "Lobster Claw", "1"),
    (35, "Blue Floral Drop Pendant Necklace", "gold-tone necklace with a blue floral pendant and tiny drop accent", "blue floral pendant", "Pendant Necklace", "Floral / Color Stone", "Lobster Claw", "1"),
    (36, "Black Clover Drop Earrings", "gold-tone drop earrings with black clover charms", "black clover drops", "Drop Earrings", "Clover / Minimal", "Hook / Drop", "1 Pair"),
    (37, "Butterfly Crystal Pendant Necklace", "gold-tone necklace with a sparkling butterfly pendant", "butterfly crystal pendant", "Pendant Necklace", "Butterfly / Crystal", "Lobster Claw", "1"),
    (38, "Tiny Heart Solitaire Necklace", "minimal necklace with a tiny heart-like solitaire charm", "tiny solitaire heart charm", "Pendant Necklace", "Heart / Minimal", "Lobster Claw", "1"),
    (39, "Rainbow Gem Charm Necklace", "gold-tone necklace with colorful gem-like dangling charms", "multicolor charm stones", "Charm Necklace", "Rainbow / Gem", "Lobster Claw", "1"),
    (40, "Silver Crystal Tennis Necklace", "silver-tone necklace with a continuous crystal tennis-chain look", "clear crystal chain", "Tennis Necklace", "Classic / Crystal", "Lobster Claw", "1"),
    (41, "Pearl Heart Drop Earrings", "gold-tone drop earrings with pearl-like heart charms", "pearl heart drops", "Drop Earrings", "Heart / Pearl", "Hook / Drop", "1 Pair"),
    (42, "Layered Heart Charm Necklace", "layered necklace with mixed chain details and a gold heart pendant", "heart charm pendant", "Layered Necklace", "Heart / Layered", "Lobster Claw", "1"),
    (43, "Crystal Bar Hoop Earrings", "gold-tone hoop earrings with a slim crystal bar detail", "crystal bar accent", "Hoop Earrings", "Bar / Crystal", "Hinged Hoop", "1 Pair"),
    (44, "Multicolor Bead Station Necklace", "delicate necklace with spaced pearl-like and colorful bead stations", "multicolor bead stations", "Station Necklace", "Bead / Minimal", "Lobster Claw", "1"),
    (45, "Cherry Crystal Hoop Earrings", "gold-tone hoop earrings with sparkling cherry-inspired crystal drops", "cherry crystal drops", "Hoop Earrings", "Cherry / Crystal", "Hinged Hoop", "1 Pair"),
    (46, "Pink Crystal Charm Hoop Earrings", "gold-tone hoop earrings with mixed clear and pink crystal charm drops", "pink and clear crystal charms", "Hoop Earrings", "Charm / Crystal", "Hinged Hoop", "1 Pair"),
    (47, "Twisted Link Hoop Earrings", "gold-tone hoop earrings with a bold twisted link texture", "twisted link detail", "Hoop Earrings", "Link / Textured", "Post / Hoop", "1 Pair"),
]


def product_copy(title, visual, accent, jtype, design, closure, qty):
    material = "Stainless Steel" if "Thread Bracelet" not in jtype else "Textile Cord / Alloy Accents"
    plating = "18K Gold Tone" if "Two-Tone" not in title and "Silver" not in title and "Aqua" not in title and "Thread" not in jtype else (
        "Two-Tone Gold & Silver Finish" if "Two-Tone" in title else "Silver Tone" if "Silver" in title or "Aqua" in title else "Textile / Gold Tone Accents"
    )
    desc = [
        f"Add a refined finishing touch to your jewellery collection with our {title}. Designed as a {visual}, this piece brings an elegant balance of everyday charm and polished detail.",
        f"The {accent} create a distinctive focal point while the clean silhouette keeps the style easy to pair with casual looks, festive outfits, and special-occasion styling.",
        f"Perfect for everyday wear, gifting, celebrations, or layering with your favorite pieces, the {title} is a versatile addition to any jewellery collection.",
    ]
    outro = [
        f"Introducing the {title}, a thoughtfully designed piece made to add graceful detail to your everyday style. Its {design.lower()} aesthetic gives it a distinctive look while keeping it wearable and easy to style.",
        f"Finished with a polished {plating.lower()}, this piece pairs beautifully with both minimal and dressier outfits. Whether worn alone or styled with other jewellery, it offers a simple way to elevate your look.",
    ]
    specs = [
        ("Material", material),
        ("Plating / Finish", plating),
        ("Jewellery Type", jtype),
        ("Design", design),
        ("Color / Detail", accent),
        ("Closure Type", closure),
        ("Net Quantity", qty),
    ]
    return desc, specs, outro


def p(text, style=None):
    if style:
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{escape(text)}</w:t></w:r></w:p>'
    return f'<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>'


def bold_p(prefix, bold_text, suffix=""):
    return (
        '<w:p><w:r><w:t>' + escape(prefix) + '</w:t></w:r>'
        '<w:r><w:rPr><w:b/></w:rPr><w:t>' + escape(bold_text) + '</w:t></w:r>'
        '<w:r><w:t>' + escape(suffix) + '</w:t></w:r></w:p>'
    )


def paragraph_with_bold_phrase(text, phrase):
    if phrase not in text:
        return p(text)
    before, after = text.split(phrase, 1)
    return bold_p(before, phrase, after)


def table(rows):
    xml = ['<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblBorders>'
           '<w:top w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '<w:left w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '<w:right w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/>'
           '</w:tblBorders></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="6360"/></w:tblGrid>']
    for a, b in rows:
        xml.append('<w:tr>')
        for txt, is_header in [(a, True), (b, False)]:
            xml.append('<w:tc><w:tcPr><w:tcW w:w="' + ("3000" if is_header else "6360") + '" w:type="dxa"/>'
                       '<w:tcMar><w:top w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/>'
                       '<w:start w:w="120" w:type="dxa"/><w:end w:w="120" w:type="dxa"/></w:tcMar></w:tcPr>'
                       '<w:p><w:r>')
            if is_header:
                xml.append('<w:rPr><w:b/></w:rPr>')
            xml.append('<w:t>' + escape(txt) + '</w:t></w:r></w:p></w:tc>')
        xml.append('</w:tr>')
    xml.append('</w:tbl>')
    return "".join(xml)


def sect_pr():
    return ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" '
            'w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')


def make_document_xml():
    body = []
    body.append(p("Shopify Product Titles and Descriptions", "Title"))
    body.append(p("Generated from product image folders under New. Each section heading matches the source folder name."))
    for folder, title, visual, accent, jtype, design, closure, qty in PRODUCTS:
        body.append(p(f"Folder {folder}", "Heading1"))
        body.append(p(title, "Heading2"))
        desc, specs, outro = product_copy(title, visual, accent, jtype, design, closure, qty)
        body.append(p("Description", "Heading3"))
        for para in desc:
            body.append(paragraph_with_bold_phrase(para, title))
        body.append(p("Specifications", "Heading3"))
        body.append(table(specs))
        body.append(p("Care for Your Jewelry", "Heading3"))
        body.append(bold_p("To keep your ", title, " looking beautiful, store it in a soft pouch or jewellery box when not in use. Avoid direct contact with perfumes, lotions, cosmetics, harsh chemicals, and excessive moisture."))
        body.append(p("After wearing, gently wipe the piece with a soft, dry cloth to remove any residue and maintain its polished appearance. Store it separately from other jewellery to help prevent scratches and tangling."))
        body.append(p("Customer Satisfaction Guaranteed", "Heading3"))
        body.append(bold_p("We take pride in offering thoughtfully designed jewellery that adds elegance to your everyday style. We want you to love your ", title, ", and our customer service team is always here to assist you with any questions or concerns."))
        body.append(p(f"Order Your {title} Today!", "Heading3"))
        body.append(bold_p("Add this beautiful piece to your jewellery collection with the ", title, ". Its elegant design makes it versatile enough for everyday styling while adding a polished finish to special-occasion outfits."))
        body.append(p(f"Whether you're treating yourself or looking for a meaningful gift, this jewellery piece is a beautiful choice. Add to Cart today and complete your look with effortless shine."))
        body.append(p(f"{title}: Effortless Everyday Elegance", "Heading2"))
        for para in outro:
            body.append(p(para))
    body.append(sect_pr())
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>' + "".join(body) + '</w:body></w:document>')


CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'''

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="180"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="36"/><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:sz w:val="32"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:sz w:val="26"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:sz w:val="24"/><w:color w:val="434343"/></w:rPr></w:style>
</w:styles>'''


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/document.xml", make_document_xml())
    print(OUT.resolve())


if __name__ == "__main__":
    main()
