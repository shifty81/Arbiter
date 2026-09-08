# Cortex Git Safety Ref Contract

Reserved ref namespace:
`refs/cortex/checkpoints/`

A checkpoint:
1. creates a temporary alternate index under project Cortex state;
2. seeds it from HEAD or an empty tree;
3. stages the working tree into that alternate index only;
4. writes a tree object;
5. creates a commit-tree object using the Cortex recovery identity;
6. updates only the reserved recovery ref;
7. removes the temporary index.

The user's checked-out branch and real Git index remain unchanged.

Restore remains a later explicit-preview/approval operation.
