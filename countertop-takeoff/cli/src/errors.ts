import { Effect, Schema } from "effect"

/** A fact in job.json needs correction before it can be used. */
export class JobError extends Schema.TaggedError<JobError>()("JobError", {
  message: Schema.String,
}) {}

/** A saved file could not be read, decoded, or written. */
export class FileError extends Schema.TaggedError<FileError>()("FileError", {
  message: Schema.String,
}) {}

/** A tool is absent, crashed, or replied outside its contract. */
export class KernelError extends Schema.TaggedError<KernelError>()("KernelError", {
  message: Schema.String,
}) {}

/** The requested operation is not allowed in the current job state. */
export class WorkflowError extends Schema.TaggedError<WorkflowError>()("WorkflowError", {
  message: Schema.String,
}) {}

/** The CLI maps every expected failure to one plain message and exit code 1. */
export type TakeoffError = JobError | FileError | KernelError | WorkflowError

/** Decode a JSON boundary, keeping parser details out of Dad's messages. */
export const decodeJson = <A>(schema: Schema.Schema<A>, text: string, error: TakeoffError) =>
  Effect.try({ try: (): unknown => JSON.parse(text), catch: () => error }).pipe(
    Effect.flatMap(Schema.decodeUnknownEffect(schema, { onExcessProperty: "error" })),
    Effect.mapError(() => error),
  )
