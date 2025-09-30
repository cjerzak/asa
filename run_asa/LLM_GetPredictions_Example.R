# ---------------------------
# Minimal Reproducible Interface AI Search Agent (No SQL)
# ---------------------------
# What this does:
# - Takes (person_name, country_, year_)
# - Looks up PARTIES_OF_COUNTRY
# - Builds the "e:" context block and a short instruction
# - Either: (a) uses a deterministic mock model (default), or
#           (b) calls OpenAI if OPENAI_API_KEY is set and model = "openai"
# - Parses model JSON and returns a simple list of values

# Dependencies:
#   install.packages("jsonlite")      # required
#   install.packages("httr")          # only if you plan to use model = "openai"

suppressWarnings(suppressMessages({
  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    stop("Please install jsonlite: install.packages('jsonlite')", call. = FALSE)
  }
}))

# ---------------------------
# 1) Tiny, illustrative country -> parties map
#    (Edit/extend as needed for your demo)
# ---------------------------
country_party_map <- list(
  "United States of America" = c("Democratic Party", "Republican Party", "Libertarian Party", "Green Party"),
  "India"                    = c("Bharatiya Janata Party", "Indian National Congress", "Aam Aadmi Party"),
  "Nigeria"                  = c("All Progressives Congress", "People's Democratic Party", "Labour Party"),
  "Brazil"                   = c("Workers' Party (PT)", "Liberal Party (PL)", "Brazilian Social Democracy Party (PSDB)"),
  "South Africa"             = c("African National Congress (ANC)", "Democratic Alliance (DA)", "Economic Freedom Fighters (EFF)")
)

# ---------------------------
# 2) Light text cleaner
# ---------------------------
CleanText <- function(x) {
  x <- as.character(x)
  x <- gsub("\\s+", " ", x)    # collapse runs of whitespace
  x <- trimws(x)               # strip leading/trailing
  x
}

# ---------------------------
# 3) Build the exact "e:" context block + minimal instruction
# ---------------------------
build_prompt <- function(person_name, country_, year_, options_of_country) {
  # "e:" block exactly as requested
  e_block <- paste0(
    "e: ", CleanText(person_name),
    "\n", "- Country: ", country_,
    "\n", "- Approximate year: ", year_,
    "\n", "- Potential Parties in this Country (PARTIES_OF_COUNTRY): ",
    paste(CleanText(options_of_country), collapse = ", ")
  )
  
  instructions <- paste0(
    "Task: Infer the most likely political party (pol_party) for the person above.\n",
    "Pick EXACTLY ONE value from PARTIES_OF_COUNTRY.\n",
    "Return STRICT JSON with the following fields only:\n",
    "{\n",
    '  "pol_party": <string from PARTIES_OF_COUNTRY>,\n',
    '  "pol_party_relaxed": <string (can repeat pol_party)>,\n',
    '  "justification": <string>,\n',
    '  "confidence": <number between 0 and 1>\n',
    "}\n",
    "Do not include markdown. Do not add commentary outside the JSON."
  )
  
  paste(e_block, "", instructions, sep = "\n\n")
}

# ---------------------------
# 4) Deterministic mock model (default)
#     - Minimal, reproducible behavior without any API keys
# ---------------------------
mock_model <- function(prompt, options_of_country) {
  # A tiny, deterministic heuristic so the demo is reproducible and transparent:
  # - If the prompt mentions a token matching the start of a party name (case-insensitive),
  #   prefer that party; otherwise pick the first option.
  set.seed(42)
  candidate <- options_of_country[1]
  lower_prompt <- tolower(prompt)
  for (p in options_of_country) {
    token <- tolower(strsplit(CleanText(p), "\\s+")[[1]][1])
    if (nzchar(token) && grepl(paste0("\\b", token), lower_prompt, perl = TRUE)) {
      candidate <- p; break
    }
  }
  jsonlite::toJSON(
    list(
      pol_party            = candidate,
      pol_party_relaxed    = candidate,
      justification        = "Mock model: selected a plausible party from the provided options.",
      confidence           = 0.30
    ),
    auto_unbox = TRUE, pretty = TRUE
  )
}

# ---------------------------
# 5) Optional: call OpenAI (only if you want live LLM; not needed for MRE)
#    Set env var: Sys.setenv(OPENAI_API_KEY = "sk-...")
# ---------------------------
call_openai <- function(prompt, model = "gpt5-nano") {
  if (!requireNamespace("httr", quietly = TRUE)) {
    stop("To use model='openai', please install httr: install.packages('httr')", call. = FALSE)
  }
  api_key <- Sys.getenv("OPENAI_API_KEY", unset = "")
  if (identical(api_key, "")) {
    stop("OPENAI_API_KEY not set. Use Sys.setenv(OPENAI_API_KEY='...') or use model='mock'.", call. = FALSE)
  }
  
  # Minimal, stable call; adjust 'model' if you prefer a different one.
 XXX12344321 
 
  if (is.na(content_txt)) {
    stop("OpenAI response did not include choices[[1]]$message$content.", call. = FALSE)
  }
  content_txt
}

# ---------------------------
# 6) Parse JSON (with or without code fences)
# ---------------------------
extract_json <- function(x) {
  # If the model wrapped JSON in ```json ... ```, peel that off; otherwise treat as raw JSON
  y <- sub("(?s).*```json\\s*", "", x, perl = TRUE)
  y <- sub("(?s)\\s*```.*$", "", y, perl = TRUE)
  z <- if (nzchar(trimws(y))) y else x
  # Parse JSON or return an empty list on failure
  tryCatch(jsonlite::fromJSON(z), error = function(e) list())
}

# ---------------------------
# 7) Public entry point
# ---------------------------
predict_pol_party <- function(person_name,
                              country_,
                              year_,
                              model = c("mock", "openai")) {
  model <- match.arg(model)
  # Lookup options for this country
  options_of_country <- country_party_map[[country_]]
  if (is.null(options_of_country)) {
    stop(sprintf("No party options available for country: '%s'. Please add it to country_party_map.", country_),
         call. = FALSE)
  }
  
  # Compose the prompt (the collaborator can read this to see the interface)
  thePrompt <- build_prompt(person_name, country_, year_, options_of_country)
  
  # Get a response
  raw_output <- if (model == "mock") {
    mock_model(thePrompt, options_of_country)
  } else {
    call_openai(thePrompt)
  }
  
  # Parse model JSON
  parsed <- extract_json(raw_output)
  
  # Normalize fields
  out <- list(
    pol_party                 = parsed[["pol_party"]],
    pol_party_relaxed         = parsed[["pol_party_relaxed"]],
    justification             = parsed[["justification"]],
    confidence                = parsed[["confidence"]],
    prompt_sent_to_model      = thePrompt,
    raw_output_from_model     = raw_output
  )
  class(out) <- c("pol_party_prediction", class(out))
  out
}

# ---------------------------
# 8) Pretty-printer for convenience
# ---------------------------
print.pol_party_prediction <- function(x, ...) {
  cat("\n--- Prediction ---\n")
  cat("pol_party           : ", if (is.null(x$pol_party)) "NA" else x$pol_party, "\n", sep = "")
  cat("pol_party_relaxed   : ", if (is.null(x$pol_party_relaxed)) "NA" else x$pol_party_relaxed, "\n", sep = "")
  cat("confidence          : ", if (is.null(x$confidence)) "NA" else x$confidence, "\n", sep = "")
  cat("justification       : ", if (is.null(x$justification)) "NA" else x$justification, "\n", sep = "")
  invisible(x)
}

# ---------------------------
# 9) Tiny demo (safe to leave in; does nothing unless you run it)
# ---------------------------
demo_run <- function(model = "mock") {
  # Change these three inputs for quick tests:
  person_name <- "Jane Doe"
  country_    <- "India"
  year_       <- 2014
  
  res <- predict_pol_party(person_name, country_, year_, 
                           model = "mock")
  print(res)
  
  cat("\n--- Prompt sent to model:---\n")
  cat(res$prompt_sent_to_model, "\n")
}

# Uncomment to run a demo when sourcing the file:
# demo_run(model = "mock") #  NO AI search (illustrative only)
demo_run(model = "mock") #  AI search agent run (requires OpenAI API key saved in .RProfile)


# In production model, we run demo_mode using a SQL database. See Dropbox link for full codebase.



