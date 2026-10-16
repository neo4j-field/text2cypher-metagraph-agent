
// 1) run this and save to CSV
WITH {
    labelsToSkip: ['inDataset','graph','uri']
} as params
CALL db.labels() YIELD label 
WITH params, label WHERE NOT label STARTS WITH '__'
ORDER BY label

CALL (params, label) {
    MATCH (n:$(label))
    WITH n
    LIMIT 100
    WITH apoc.text.join([key in keys(n) 
        WHERE NOT key IN params.labelsToSkip
          AND n[key] IS NOT NULL 
          AND NOT apoc.meta.cypher.type(n[key]) CONTAINS 'LIST'
          AND n[key] <> '' 
        | key + ': ' + n[key]], ', ') as propString
    RETURN distinct propString
    LIMIT 10
}

WITH label, trim(apoc.text.join(collect(propString), '\n')) as propStrings
RETURN label, propStrings
ORDER BY label;



// prompt for LLM to generate semantic_text
// NOTE: This has been saved to node_label_text_prompt.txt
/*
Given the input CSV of label (node label), and sample key/value properties for instances of that node label (propStrings)

generate a semantic text description that can be used as the basis for a text embedding to enable vector search

then for each label generate a Cypher statement that ends with a semi-colon like this

MATCH (nl:__NodeLabel__ {label: '<label>'})
SET nl.semantic_text = '<semantic text>';

// example
MATCH (nl:__NodeLabel__ {label: 'Sample'})
SET nl.semantic_text = 'Definition of sample label.';

<csv>...contents of CSV...</csv>
*/

