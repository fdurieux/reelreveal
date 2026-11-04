Feature: Honest Reel analysis
  Scenario: LPs are the default target
    Given the CLI defaults
    Then the identification target is "LPs and record sleeves"

  Scenario: Users can request other items
    Given the CLI target is "sneakers"
    Then the identification target is "sneakers"

  Scenario: Inaccessible Instagram videos give recovery options
    Given Instagram retrieval is unavailable
    When a Reel is downloaded
    Then the error suggests a local video

  Scenario: Extraction alone does not claim identification
    Given a sampled frame without a vision provider
    When the frame is analyzed
    Then no identifications are reported
