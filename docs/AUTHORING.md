# Writing a good flow

For whoever builds a client's flow in the Editor. A flow is a series of questions a tech answers;
every path ends in a resolution. A good one is short to read, fast to search, and honest about what
to try next.

## Start from the client's real calls

1. Collect the 10–20 most common reasons their techs get stuck. Use their ticket titles, not ours.
2. Write each as a first question a tech would recognise ("No internet", not "Network diagnostics").
3. Draft the flow as text first (see the outline importer below), then refine it in the Editor.

## Questions and answers

- **One thing per question.** If a question needs "and", it is two questions.
- **Ask what the tech can see or do**, not what they must know: "Is the Wi-Fi icon showing a cross?"
- **Keep answers short**, ideally two to six per step. One answer means it isn't a decision; fold it
  into the previous step's note. Over six is hard to scan; split it.
- Put detail in the **note** (a hint under the question, web addresses become links), and a
  **screenshot** where the tech must find something on screen.
- Every answer is either a next question or an ending. No dead ends; Validate catches them.

## Resolutions

- Say **what to do**, in the order to do it. "Restart" is thin; "Restart the router, wait two minutes,
  then reload the page" is a fix.
- When several paths end in the same fix, make it a **shared resolution** (Shared… button). It is
  written once, and analytics count every path to it as one ending.
- Add a **KB article** for background that doesn't belong in a step (a policy, a long procedure,
  a vendor guide). Attach it to the steps and resolutions where techs would reach for it.
- Set an **escalation resolution**. When a tech marks every suggested fix "didn't work", the Player
  offers it instead of leaving them stuck.

## Tags (search)

The Player's search box finds steps by their question, note and tags, with tags weighted highest.

- Tag with the words a tech types: symptoms, error messages, product names ("blue screen", "0x0000007B",
  "outlook"). Synonyms help; spelling variants help.
- Tag the **first step** of each topic most. A search lands there and the tech follows the flow.
- Leave tags off steps nobody would search for ("Did that fix it?").

## Faster building in the Editor

- **＋ Step** beside an answer makes the next step and links it.
- **Duplicate** copies a step as a starting point for a sibling.
- **Import…** turns an indented outline into steps:

```
Does the PC power on?  [tags: power, boot]
  - Yes
    Does it reach the login screen?
      - Yes => Run the update again from Safe Mode.
      - No => Escalate to hardware.
  - No => Check the power cable and wall socket.
```

## Before you ship

1. **Validate.** Fix every error; read the warnings (a loop back to a step is sometimes intended).
   The ✎ writing hints are suggestions: missing tags, over-long text, thin resolutions.
2. **Walk it in Live Test**, taking the paths a tech would, including "no" and "didn't work".
3. Set the **client** and **version** (they are stamped into every report and log).
4. After release, review real use: load the outcome logs in **Analytics**. Cards where techs drop
   off and endings that get rejected are the next edits.

## Habits that keep a flow healthy

- **IDs are identity.** Don't reuse a step, resolution or article id for something else; analytics
  join on them across versions.
- Don't put customer details in the flow itself. Notes and tickets are entered by the tech at run time.
- Change a flow in small, versioned steps and bump the version, so a month of logs can be compared.
