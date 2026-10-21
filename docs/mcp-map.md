# The MCP Map, rules v1

A standard picture of an app's MCP architecture: what it calls, in what order, how long each call takes, and what makes it slow. It is made to be sent: in a report, a pull request, a README or a slide. Anyone who knows these six rules reads any MCP Map the same way.

FlowForge draws one from your code (Flow map → **Export**). The rules don't depend on FlowForge, so anyone may draw one by hand or with another tool.

## The six rules

1. **Lanes are kinds,** always in this order, top to bottom:

   | Lane | Holds |
   |---|---|
   | Decisions | the `if`s that choose what runs |
   | LLMs | models the code asks |
   | MCP servers | servers the app starts or reaches |
   | APIs | HTTP services |
   | Local programs | programs run on the same machine |

2. **Time runs left to right.** A call starts when its inputs are ready. Its bar is as long as the call takes, so long bars are what make an app slow. A map of dependencies only (no order) has no time axis: its blocks sit in their lanes in name order.

3. **One shape per kind,** readable in black and white:

   | Shape | Kind |
   |---|---|
   | double ring ◎ | entry point (where a flow begins) |
   | ring with a dot ⊙ | LLM |
   | hexagon ⬡ | MCP server |
   | rounded square ▢ | API |
   | triangle △ | local program |
   | diamond ◇ | decision |
   | filled square ■ | stop (the code returns early) |

4. **Lines:**
   - a line goes from the end of one call to the start of the call that waits for it;
   - the **thick** line is the critical path, the chain that sets the total time;
   - a **dashed** line means the call is reached through another server;
   - a **dashed bar** is an estimate, not a measurement.

5. **Marks:**
   - a dot is health: teal up, amber needs a look, coral down;
   - ✎ means the call writes something;
   - ↻ means it repeats in a loop.

6. **Every block has a source.** The map travels with its data (Flow JSON), which gives each block's file and line, so anyone can check it against the code.

Every map carries a **title block** (the app, where it was read from, the date, the counts) and a **key**.

## Formats

| Format | For |
|---|---|
| SVG | documents and the web: sharp at any size |
| PNG (2×) | slides and chat |
| PDF | reports: A4 landscape, through the print dialog |
| Mermaid | READMEs and pull requests: GitHub draws it |
| Flow JSON | tools: the data behind the map, with every `file:line` |

Code excerpts in an export are masked first: FlowForge catches known key formats, and an export never contains a key value.
