# DOCUMENTS
This directory contains all project documentation, including the Design Doc, Prompting Protocol, and Remediation Ledger.

Excel Link for Remediation Ledger: 
https://docs.google.com/spreadsheets/d/1hdHh30pgJRnWd4VIoceJsj7AAvxvCbOJsMZ1v115Ids/edit?usp=sharing


-fix_id (Fix ID): A unique, sequential number for every single change you make. This makes it easy to refer to specific fixes 
(e.g., "As seen in Fix #17...").

-timestamp (Timestamp): The date and time you implemented the fix. This helps create a timeline of your work and can reveal how long it took to get a piece of code from "broken" to "working."

-problem_area (Problem Area): The high-level section of the project this fix applies to. This helps you categorize your efforts.
Shortest Path, Subgraph Isomorphism, Build System

-file_path (File Path): The specific file you modified.

-lines_changed (Lines Changed): A quantitative measure of the size of the change. This helps you objectively measure how much of the LLM's code you had to alter. Use git diff or your editor to find this.
*Example: +5, -2 (meaning you added 5 lines and removed 2)*

-time_spent_min (Time Spent in Minutes): This is one of your most critical metrics. It's the total time, in minutes, it took you to diagnose the problem, figure out the solution, and implement the fix. This directly measures the "human engineering effort."

-category (Category): Classifies the type of problem you solved. This is crucial for your final analysis to identify what kinds of mistakes the LLM makes most often.
 *Example:
  *Compile-time Error: The code did not compile.
  *Runtime Bug: The code compiled but crashed or gave the wrong answer.
  *Algorithmic Flaw: The code ran but used a fundamentally incorrect algorithm (e.g., wrong complexity, wouldn't terminate).
  *Performance Optimization: The code was correct but slow, and you made a change to improve its speed or memory usage.
 *

-rationale (Rationale): This is the most important column for your final report. In one or two sentences, explain why the fix was necessary. What mistake did the LLM make?

-impact_on_correctness (Impact on Correctness): Describe the effect of your change on the program's ability to produce the right answer.

-impact_on_performance (Impact on Performance): Describe the measured effect of your change on the program's speed or memory usage.
 *Example: "N/A" (for correctness fixes), or "Reduces runtime by 1.2 seconds on the roadNet-CA dataset." or "Reduces peak memory usage by 50MB."*