You job is to write the documentation for the topic of the folder you are currently in.

# Guiding principles:
- the code is the source of truth. If a notion doc says one thing, but the code says another, then go with the code.
- Cite everything in code. You should be able to point to exactly where this is done.
- Don't mention use cases not supported in code or a notion doc specifically

# Information Sources
A large amount of information has been gathered for you already. It should be present in this folder.

## Navigating the repo

You should be in a folder like this:
repo root = `git rev-parse --show-toplevel`
<repo root>/<service>/<docs>/<topic>/
So if you're in the example-service service folder, writing documentation for the topic schedules, you should be in:
<repo root>/example-service/docs/schedules

You should write the final topic at
<repo root>/example-service/docs/<topic>.md

###  Documentation Folder Structure
```
<repo root>/<service>/<docs>/<topic>/
├── intro.md
├── PRDs.md
├── RFCs.md
├── notion_pages.md
├── linear_projects.md
├── linear_issues.md
├── PRs.md
├── timeline.md
├── prds/
│   ├── prd_1.md
│   ├── prd_2.md
│   └── ...
└── notion_pages/
    ├── notion_page_1.md
    ├── notion_page_2.md
    └── ...
```

### Documentation Folder File Descriptions

- **intro.md**: A comprehensive guide introducing the topic, including relevant service files and context
- **PRDs.md**: Aggregated digest of Product Requirements Documents from Google Drive with creation dates, update dates, and original links
- **RFCs.md**: Aggregated digest of Request for Comments documents from Notion with metadata and links
- **notion_pages.md**: Comprehensive digest of all related Notion pages with metadata
- **linear_projects.md**: Summary of Linear projects, focusing on Team A, Team B, and Team C teams
- **linear_issues.md**: Compilation of Linear issues from the associated projects
- **PRs.md**: Analysis of GitHub Pull Requests related to the topic with code descriptions
- **timeline.md**: Chronological timeline created after reading all other documents
- **prds/**: Directory containing individual PRD files downloaded and converted to markdown
- **notion_pages/**: Directory containing individual Notion pages converted to markdown format

# Writing Style
Focus on long-form discussion of how it works rather than bullet point lists. Not flowing prose, informative direct speech. Direct compact technical communication. You can have bullet points, but only where they make sense as actual lists of items. Bullet points are fine for actual lists of discrete items, but should be converted to prose when describing processes, features, or explanations.

# Documentation Template
Here is the format in which you should write the documentation for this topic:
<documentation-template>

--------
# <Topic Name>

# Table of Contents

# Overview

<intro paragraph that gives a brief overview of the topic, and what it does. Write this last as a conslidation summary once we have the rest of the information to draw upon>

## Background

<A place  to write out the or Write this 2nd to last as a conslidation summary once we have the rest of the information to draw upon>

### Terminology

<Terminology specific to this topic>

### Concepts

<concepts that are realted and need to be understood to understand the topic. Give only a brief description here>

### History
< how it has progressed over time - v1, v2, projects done to re-work it, what those changes did/accomplished and how they altered it, etc. Timeline is super important here>

# Implementation Details

### Contract
What is guaranteed and not guaranteed by this concept.


### Backend
#### Data Model

<crawl through the database model in example-service/docs and pluck out anything related to the topic. Support by citiing spefic elements in some models.py file somewhere>

#### example-service API Endpoints


#### Permissions

< What permissions are needed/used during the course of interfacing with the items in this topic's endpoints>

#### public-api endpoints
Add any public-api endpoints associated with this topic

### Firmware
Firmware for access is in the device-service and device-service-common service folders

## device-service-common

## device-service

# Appendix

### Related Merged Reference Pull Requests

### Related Notion Docs (PRDs, RFCs, Projects, etc)

### Linear Projects

### Linear Issues
</documentation-template>

