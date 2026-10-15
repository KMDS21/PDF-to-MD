---
title: "samples"
converter: PDF-to-MD
sources: 5
converted: 2026-10-15T21:54:14Z
---

# 📚 samples

*Combined conversion of 5 file(s). Each source starts after a horizontal rule.*


---

**📄 Source: `sample_grades.xlsx`**  
*Converted by xlsx (openpyxl)*

## Midterm Results

| Student ID | Name | Midterm | Final | Passed |
|---|---|---|---|---|
| 1001 | Amal | 78.5 | 82 | TRUE |
| 1002 | Nimal | 55 | 61.25 | TRUE |
| 1003 | Kasun | 41.75 | 49 | FALSE |
| 1004 | Ishara | 88 |  | TRUE |

## Grading Notes

| Grade | Range |
|---|---|
| A | 75-100 |
| B | 65-74 |
| C | 50-64 |
| F | 0-49 |

---

**📄 Source: `sample_lecture.pdf`**  
*Converted by pdf (PyMuPDF)*

# Lecture 3: Neural Networks

![Image on page 1](samples_assets/p1_img62.png)

Course: Deep Learning Fundamentals

## 1. Introduction

A neural network is a computational model inspired by the structure of biological brains. It consists of layers of interconnected neurons that propagate signals.

Key topics covered today:

- Forward propagation and activations

- Loss functions such as cross-entropy

- Gradient descent with learning rate alpha

The update rule is:

$$
θ = θ - α ∇J(θ)
$$

## 2. Comparison of activation functions

| Activation | Range | Use case |
|---|---|---|
| ReLU | 0 to inf | Hidden layers |
| Sigmoid | 0 to 1 | Binary output |
| Softmax | 0 to 1 | Multi-class |

## 2. Section content

Paragraph 1 on page 2 covers training dynamics, regularization and evaluation metrics.

Paragraph 2 on page 2 covers training dynamics, regularization and evaluation metrics.

Paragraph 3 on page 2 covers training dynamics, regularization and evaluation metrics.

Paragraph 4 on page 2 covers training dynamics, regularization and evaluation metrics.

## 3. Section content

Paragraph 1 on page 3 covers training dynamics, regularization and evaluation metrics.

Paragraph 2 on page 3 covers training dynamics, regularization and evaluation metrics.

Paragraph 3 on page 3 covers training dynamics, regularization and evaluation metrics.

Paragraph 4 on page 3 covers training dynamics, regularization and evaluation metrics.

## 4. Section content

Paragraph 1 on page 4 covers training dynamics, regularization and evaluation metrics.

Paragraph 2 on page 4 covers training dynamics, regularization and evaluation metrics.

Paragraph 3 on page 4 covers training dynamics, regularization and evaluation metrics.

Paragraph 4 on page 4 covers training dynamics, regularization and evaluation metrics.

---

**📄 Source: `sample_lecture.pptx`**  
*Converted by pptx (python-pptx)*

## Slide 1: Week 5: Database Indexing

- Databases II — Lecture Slides

---

## Slide 2: Why Indexes Matter

- Full table scan costs O(n)
  - B-tree indexes give O(log n) lookups
  - Hash indexes give O(1) equality lookup
    - but no range support
- Composite indexes follow leftmost-prefix rule

**Notes:**

> Emphasize the exam question from 2023: why not always hash indexes?

---

## Slide 3: Index type comparison

| Type | Lookup | Range |
|---|---|---|
| B-tree | O(log n) | Yes |
| Hash | O(1) | No |

---

## Slide 4: Query plan example

![Slide 4 image](samples_assets/slide4_img3.png)

**Notes:**

> Show EXPLAIN output live in demo.

---

**📄 Source: `sample_notes.docx`**  
*Converted by docx (python-docx)*

# Operating Systems — Week 2 Notes

## 1. Process Scheduling

The scheduler decides which process runs next. **Critical concept:** *context switching has a cost.*

> Common algorithms:

- Round Robin
- Shortest Job First
- Multi-level Feedback Queue

### 1.1 Comparison

| Algorithm | Preemptive |
|---|---|
| Round Robin | Yes |
| SJF | Sometimes |

![image](samples_assets/img3.png)

---

## 2. Deadlocks

Four necessary conditions must hold simultaneously.

---

**📄 Source: `whiteboard.png`**  
*Converted by image (OCR)*

![whiteboard](samples_assets/whiteboard.png)
