# Error Semantics

A tool that cannot complete returns an MCP tool error: the response has `isError: true` and a single text content item holding the message. A tool that completes returns its typed result. A partial outcome inside a successful result, such as a failed entry in `batch_add_objects`, is reported in that result's own fields.

## Error Messages

The server rewrites exceptions raised by `idfkit` into messages in the following categories:

| Category | Message form |
| --- | --- |
| Validation failure | `Validation failed: ...` |
| Unknown object type | `Unknown object type: '<type>'`, followed by a documentation search link |
| Duplicate object name | `Duplicate <type> object with name '<name>'. It already exists in the model; use update_object to change its fields.` |
| Other missing key | `Not found: ...` |
| Missing schema or version | `Schema not found: ...` or `Version not found: ...` |
| Simulation failure | `Simulation error: ...` |
| Missing EnergyPlus installation | `EnergyPlus not found. Install EnergyPlus or set the ENERGYPLUS_DIR environment variable.` |
| Any other exception | `<ExceptionName>: ...`, for example `InvalidFieldError: Invalid field 'x' for object type 'Zone'` |

A precondition failure, such as calling a model tool before `load_model` or `new_model`, returns the precondition's own message, for example `No model loaded. Use load_model or new_model first.` Errors raised deliberately by a tool keep the message that tool wrote.

## Recommended Agent Handling

1. Check whether each tool response is an error.
2. If it is, stop any dependent calls.
3. Make the smallest argument change that the message calls for.
4. Retry that call.
5. Run the validation gates again after the recovery edits.

## Logging

An expected tool error is logged on the server at `WARNING` level as one line naming the tool, the session, the elapsed time and the message, with no traceback. An unexpected exception is logged with its traceback.
