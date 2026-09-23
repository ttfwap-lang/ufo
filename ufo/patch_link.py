import io

p = "astro_collect.py"
s = io.open(p, encoding="utf-8").read()

old1 = ('            link = find_box(boxes, "Horoscopes", exact=True, rightmost=True,\n'
        '                            y_min=700) or find_box(boxes, "Horoscopes")')
new1 = '            link = find_link(boxes)'

old2 = ('                link = find_box(boxes2, "Horoscopes", exact=True,\n'
        '                                rightmost=True, y_min=700) or \\\n'
        '                    find_box(boxes2, "Horoscopes")')
new2 = '                link = find_link(boxes2)'

n1 = s.count(old1)
n2 = s.count(old2)
s = s.replace(old1, new1).replace(old2, new2)
io.open(p, "w", encoding="utf-8").write(s)
print("replaced:", n1, n2, "| find_link uses:", s.count("find_link("))