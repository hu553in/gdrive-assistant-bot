all

# limit line length to 120 characters (ignore code blocks and tables)
rule 'MD013', :line_length => 120, :ignore_code_blocks => true, :tables => false

# allow <br> for line breaks
rule 'MD033', :allowed_elements => 'br'

# exclude !? from defaults
rule 'MD026', :punctuation => '.,;:'

# allow 1., 2., etc.
rule 'MD029', :style => 'ordered'
