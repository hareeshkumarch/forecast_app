// Storage is handled by the Python ML engine's SQLite database.
// Express routes proxy all data operations to the ML engine.
// This file is kept minimal as all persistence is in the ML engine.

export interface IStorage {}

export class MemStorage implements IStorage {}

export const storage = new MemStorage();
