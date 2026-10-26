# Heuristic Expansion Prompt

This is the prompt we gave the LLM (Claude Opus 5.5) to expand the pilot lookup tables using the
**development set** (339 trajectories). An author checked every entry it proposed against the
step and, when needed, the whole trajectory before accepting it.

The result is in [`Inceptor lookup tables.xlsx`](Inceptor%20lookup%20tables.xlsx):

| Tab | Content |
|---|---|
| **Final lookup table** | The expanded action, target-file and phase tables |
| **Lookup justification** | Each added or changed entry, with the development steps that justify it |

## What the prompt asks for

- **Input:** the pilot lookup tables (`Parser/Ground Truth/annotation_workbook.xlsx`) and the
  339 development trajectories.
- **Task:** expand the action table and the phase table.
- **Evidence:** back every new entry with justifications and concrete example steps.
- **Tables before rules:** put as much as possible into the lookup tables, and add a separate
  rule only for a case the tables cannot express.
- **Output:** two new sub-sheets, one with the final lookup table and one with the justification
  of each entry.

## Prompt (as used)

> In this session, you're tasked to expand our manually created lookup table (located in
> @"Parser/Ground Truth/annotation_workbook.xlsx") for our development set, which contains 339
> trajectories. You only need to look into the final trajectories from our pilot dataset or pilot
> trajectory.
>
> Whenever you add any entry, whether it is in the action table or in the first table, you need
> to have at least two justifications for that. It should have two or fewer concrete examples of
> which step you have added this action for.
>
> For curating the phase lookup table, the key idea is to keep expanding the lookup table and try
> to accumulate all the rules in there. We are going to create our methodology by looking up in
> the lookup table. If we cannot fit it into the lookup table, only then will we add some rules.
>
> Create a final lookup table in a separate sub-sheet, and keep another sub-sheet for the
> justification for your action category and the phase in the entry.
