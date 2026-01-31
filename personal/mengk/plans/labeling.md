In docent_core/_web/app/dashboard/[collection_id]/agent_run/[agent_run_id]/layout.tsx you can see that we have a labels tab. I'm trying to rework the labeling experience to be more intuitive.

---

TASK 1

Specifically I would like to redesign docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx:
- At the top right, I would like a singular Add Label button. No more modulating between label sets directly. We're going to handle that in the background.
    - When you click the label button, there should be an inline dropdown. In particular, it should not be a separate modal. The drop-down should Have a button at the top to create a new label set -- below that There should be buttons to select an existing label set from the list below.
    - If you click the Create Label Set button within the same drop-down, we should open a dialog to create a new label set. I'm going to implement or design this later, so just put a placeholder content there for now.

I would prefer to re-implement the Agent run labels component from scratch, so what I would recommend is to rename the existing file and function to something like Agent run labels old, and then create a new file.

And by from scratch, I really mean from scratch. You should not include any of the functionality to get the current labels and render them, or anything like that. I'm going to redesign all the cards from scratch as well.

---

TASK 2

Okay, now time to design the create label set dialog.

- The dialogue should allow the user to customize the name and schema of the label set. One thing I would like to do to make the dialogue more intuitive is to have "preset schema ideas". For example, common label types are like: binary (yes/no) judgments, Categories, Numerical Rating scales
- Another important part would be to have an intuitive schema building UI where for each of the different types of keys.
- Finally, there should obviously be a fallback to the full JSON schema editor in case what the user wants is fairly non-standard.
- The user should be able to click a button to actually post the label set.
- Note that the label set dialog should actually be shown "inside" the dropdown of the "add label" button -- make that transition smooth and everything -- perhaps it needs to be bigger than the normal dropdown.

Just stop here as I will help walk you through the rest in a bit.

---

TASK 3

Now let's design the display of labels. As you can see in the old agent run labels file, you can query for labels. I would like this query to return all of the labels across all the existing label sets for this particular agent run.

Then you should render the labels. Use the component in docent_core/_web/app/dashboard/[collection_id]/components/SchemaValueRenderer.tsx to render the label values. The card should also indicate which level it is part of.

Please design this card tastefully.

---

TASK 4

Relevant files: docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx docent_core/_web/app/dashboard/[collection_id]/components/SchemaValueRenderer.tsx

I now need a clean way to edit values rendered by the schema value renderer. As far as I can understand, the schema value renderer is fully schema-aware.

I'm not sure of the best approach here. I can imagine you might want to update the schema value renderer to have an edit mode where the keys are always the same but the values are drop-downs or numerical fields or whatever. I can also imagine that being a completely separate component.

One other consideration here is that I don't think we need to support nesting at the moment. So, objects that have lists or dictionaries nesting recursively don't need to be supported and they can just be ignored.

Help me come up with a plan. What other design questions am I not addressing?

---

TASK 5

Finally, we need to hook up the logic between selecting a label set and creating a label.

More specifically, when somebody selects a label set or creates one through the popover triggered by clicking "Add labels"  -- After they do that, what should happen is there should be a blank label object created which is put in the main area, and the user should be able to fill in the values and hit save. It should be put in the same type of card as the existing labels. However, if you hit cancel, then nothing happens. If you hit save instead of updating existing labels, you need to create a new one.

---

As you can see, Task 1-4 is already complete. Please help me with Task 5.

---

docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx
docent_core/docent/server/rest/label.py
docent_core/docent/services/label.py
docent_core/_web/app/api/labelApi.ts
docent_core/docent/db/schemas/label.py

One small detail I would like to address here is the ordering of the labels that are presented here. The solution I have in mind is to sort by most recently updated label set when pulling down the labels. That way, when I create a new label in a label set, it will be shown at the top. And when I switch to other agent runs, the same will be true.

Therefore, we will have to add an updated_at field to the label set and have that changed whenever we change a label that is inside of a label set.

Then when we grab all the labels across all the label sets, we need to make sure that sorts by updated_at.

You don't have to worry about the database migration because I will handle it later, but make sure the schema is correct.

If you have any open design questions, definitely let me know.

---

docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx

In the popover that gets activated when you click Add Label, I would like to add some polish
- Firstly, I would like to add a message above the existing label sets containing a message something like "Add label to existing label set."
- If possible, I would also like to put some small text here, creating a label set that explains that label sets are groups of labels measuring the same thing and sharing a schema.

Basiclly, I would like a concise, tasteful way to explain to a new user what is going on. It's totally fine to make the popover a little bit bigger to accommodate more text.



add some interesting metadata about the label sets, including a summary of the available fields.

---

docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx

In the dialogue for creating a label set, I would like to add a sort of subtitle right below the title that explains what's going on.

---

docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunLabels.tsx
docent_core/docent/server/rest/label.py
docent_core/docent/services/label.py
docent_core/_web/app/api/labelApi.ts
docent_core/docent/db/schemas/label.py

One thing that needs to be addressed here is that the popover activated when you click "Add label" pulls a list of all label sets. However, we actually need a different endpoint that Separates label sets with and without a label for a particular agent run. This is because you shouldn't be able to add a label to an AgentRun that already has a label for that label set.

In the popover, I would like to display The labelsets that you can add to at the very top and at the very very bottom. The labelsets that are already filled for this agent run in green so that you can't click them. It's purely cosmetic and to inform the user about what's clearly going on.
