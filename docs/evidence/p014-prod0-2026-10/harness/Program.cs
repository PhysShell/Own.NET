// PROD0 harness: runs the in-memory controls against the production binding-coverage code.
using System.Text.Json;
using OwnSharp.BindingCoverage;

return Controls.Run(new Env(), args[0], new JsonSerializerOptions { WriteIndented = true });
