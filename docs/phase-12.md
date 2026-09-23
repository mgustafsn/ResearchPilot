# Phase 12 implementation

Users can now create, delete, and merge subtopics as well as rename them. A created
subtopic receives the next free cluster id, is attached to the latest completed search
run, and is marked as user-modified. Deleting a subtopic moves its papers to
Uncategorized; merging moves the source's papers into the target, marks the target as
user-modified, and removes the source. Every reassignment clears the affected papers'
cached classification explanations. All three operations are blocked with 409 during an
active search and count as manual edits, so a later search requires explicit
confirmation before replacing them. No migration is needed; existing subtopic and
project-paper columns hold the result.
