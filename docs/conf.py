import sys, os
sys.path.append(os.path.abspath('sphinxext'))
extensions = [
          'matplotlib.sphinxext.mathmpl',
          'matplotlib.sphinxext.only_directives',
          'matplotlib.sphinxext.plot_directive',
          'sphinx.ext.autodoc',
          'sphinx.ext.doctest',
          'ipython_console_highlighting',
          'inheritance_diagram',
          'numpydoc']

templates_path = ['_templates']

source_suffix = '.rst'

master_doc = 'index'

project = u'QunatPy'

version = 'v1.0'
release = 'v1.0'

exclude_patterns = ['_build']

pygments_style = 'sphinx'

html_theme = 'default'
html_static_path = ['_static']

htmlhelp_basename = 'QunatPydoc'

latex_elements = {

latex_documents = [
  ('index', 'QunatPy.tex', u'QunatPy Documentation',
   u'Joseph Smidt', 'manual'),
]


man_pages = [
    ('index', 'qunatpy', u'QunatPy Documentation',
     [u'Joseph Smidt'], 1)
]

texinfo_documents = [
  ('index', 'QunatPy', u'QunatPy Documentation',
   u'Joseph Smidt', 'QunatPy', 'One line description of project.',
   'Miscellaneous'),
]
# How to display URL addresses: 'footnote', 'no', or 'inline'.
#texinfo_show_urls = 'footnote'
